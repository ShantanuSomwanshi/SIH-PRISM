"""
What's New Detector for BIS Standards Updates

Scrapes https://www.bis.gov.in/whats-new/?lang=en to track latest standard updates,
revisions, and new standards from BIS announcements.

Supports:
- Main page: Current What's New entries
- Archive page: Past entries with pagination (up to 10 pages)
- Extracts standard numbers from titles
- Tracks publication dates and content types
"""

import re
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class WhatsNewEntry:
    """Represents a single What's New entry from BIS"""
    title: str
    standard_id: Optional[str]  # Extracted from title (e.g., "IS 19497")
    content_type: str           # pdf, youtube, document, etc.
    published_date: Optional[datetime]
    url: Optional[str]
    size: Optional[str]
    source_page: str           # main or archive
    confidence: str = 'low'    # high, medium, or low


class WhatsNewDetector:
    """
    Scrapes BIS What's New page to detect standard updates
    
    Features:
    - Scrapes current entries from main page
    - Scrapes archive entries (up to 10 pages)
    - Extracts standard numbers from titles
    - Filters for standard-related entries
    - Tracks publication dates for change detection
    """
    
    # Standard number patterns (IS XXXX, IS XXXX:YYYY, etc.)
    STANDARD_PATTERN = re.compile(
        r'(?:as per\s+)?'
        r'IS\s+(\d+)'
        r'(?:\s*\(Part\s+\d+\))?'
        r'(?:\s*:\s*\d{4})?',
        re.IGNORECASE
    )
    
    # URLs
    MAIN_URL = "https://www.bis.gov.in/whats-new/?lang=en"
    ARCHIVE_URL = "https://www.bis.gov.in/whats-new-archive/?lang=en"
    
    # Max pages to check in archive
    MAX_ARCHIVE_PAGES = 1
    
    def __init__(self, timeout=10, retries=2, retry_base_seconds=1):
        self.timeout = timeout
        self.retries = retries
        self.retry_base_seconds = retry_base_seconds
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch and parse a webpage
        
        Args:
            url: URL to fetch
            
        Returns:
            BeautifulSoup object or None if fetch failed
        """
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return BeautifulSoup(response.content, 'html.parser')
            except requests.RequestException as exc:
                if attempt >= self.retries:
                    logger.error(f"Failed to fetch {url}: {exc}")
                    return None
                delay = self.retry_base_seconds * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning('BIS What\'s New request failed (%s), retrying in %.1fs', exc, delay)
                time.sleep(delay)
        return None
    
    def extract_standard_id(self, title: str) -> Optional[str]:
        """
        Extract standard ID from title
        
        Examples:
        - "Carbon and Low-Alloy Steel Wire Rods...IS 19497: 2026" → "IS 19497"
        - "Grant of All India First Licence...IS 17440 : 2020" → "IS 17440"
        - "Revision of IS 5175" → "IS 5175"
        
        Args:
            title: Entry title
            
        Returns:
            Standard ID (e.g., "IS 19497") or None
        """
        match = self.STANDARD_PATTERN.search(title)
        if match:
            standard_num = match.group(1)
            return f"IS {standard_num}"
        return None
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse publication date
        
        Args:
            date_str: Date string (e.g., "20 Aug, 2026")
            
        Returns:
            datetime object or None if parsing failed
        """
        try:
            return datetime.strptime(date_str.strip(), "%d %b, %Y")
        except Exception as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            return None
    
    def parse_entries_from_html(
        self,
        html: BeautifulSoup,
        source_page: str = "main"
    ) -> List[WhatsNewEntry]:
        """
        Parse What's New entries from HTML
        
        Args:
            html: BeautifulSoup object of page
            source_page: "main" or "archive"
            
        Returns:
            List of WhatsNewEntry objects
        """
        entries = []
        
        try:
            # Find all entry blocks (h2 tags with links are titles)
            title_tags = html.find_all('h2')
            
            for title_tag in title_tags:
                link = title_tag.find('a')
                if not link:
                    continue
                
                title = link.get_text(strip=True)
                if not title:
                    continue
                
                # Extract URL
                url = link.get('href', '')
                if url.count('https://') > 1:
                    # Some BIS YouTube cards concatenate two links in one href.
                    url = 'https://' + url.split('https://', 1)[1].split('https://', 1)[0]
                
                # Keep metadata inside this announcement card. Scanning all
                # following divs can associate the next card's date with this title.
                parent = None
                for candidate in title_tag.parents:
                    if (candidate.name == 'div'
                            and len(candidate.find_all('h2')) == 1
                            and re.search(r'Published\s+On\s*:', candidate.get_text(), re.I)):
                        parent = candidate
                        break
                if parent is None:
                    parent = title_tag.parent
                
                # Find content type and date in nearby elements
                content_type = "unknown"
                pub_date = None
                size = None
                
                # Search for type/date info near the title
                nearby = parent.find_all(['p', 'h3', 'div']) if parent else []
                for sibling in nearby:
                    text = sibling.get_text()
                    
                    # Look for type: pdf, youtube, etc.
                    if 'Type:' in text:
                        content_type = text.split('Type:')[-1].strip().split('\n')[0]
                    
                    # Look for size
                    if 'Size:' in text:
                        size = text.split('Size:')[-1].strip().split('\n')[0]
                    
                    # Look for published date
                    if 'Published On:' in text:
                        date_str = text.split('Published On:')[-1].strip().split('\n')[0]
                        pub_date = self.parse_date(date_str)
                        break
                
                # Extract standard ID from title
                standard_id = self.extract_standard_id(title)
                normalized_type = content_type.strip().lower()
                is_bis_pdf = bool(
                    url and url.lower().startswith('https://www.bis.gov.in/')
                    and url.lower().split('?', 1)[0].endswith('.pdf')
                )
                if standard_id and normalized_type == 'pdf' and pub_date and is_bis_pdf:
                    confidence = 'high'
                elif standard_id and (normalized_type == 'pdf' or is_bis_pdf):
                    confidence = 'medium'
                else:
                    confidence = 'low'
                
                # Only include entries related to standards
                if standard_id or any(keyword in title.lower() 
                                     for keyword in ['standard', 'revision', 'is ', 'licence']):
                    entry = WhatsNewEntry(
                        title=title,
                        standard_id=standard_id,
                        content_type=content_type,
                        published_date=pub_date,
                        url=url if url else None,
                        size=size,
                        source_page=source_page
                        , confidence=confidence
                    )
                    entries.append(entry)
                    logger.debug(f"Extracted entry: {standard_id or 'Unknown'} - {title[:50]}...")
        
        except Exception as e:
            logger.error(f"Error parsing entries from HTML: {e}")
        
        return entries
    
    def get_main_page_entries(self) -> List[WhatsNewEntry]:
        """
        Fetch and parse entries from main What's New page
        
        Returns:
            List of WhatsNewEntry objects
        """
        logger.info("Fetching main What's New page...")
        html = self.fetch_page(self.MAIN_URL)
        if not html:
            logger.warning("Failed to fetch main What's New page")
            return []
        
        entries = self.parse_entries_from_html(html, source_page="main")
        logger.info(f"Found {len(entries)} entries on main page")
        return entries
    
    def get_archive_entries(self, max_pages: int = MAX_ARCHIVE_PAGES) -> List[WhatsNewEntry]:
        """
        Fetch and parse entries from archive page (with pagination)
        
        Args:
            max_pages: Maximum number of pages to fetch (default 10)
            
        Returns:
            List of WhatsNewEntry objects
        """
        entries = []
        max_pages = max(0, min(int(max_pages), self.MAX_ARCHIVE_PAGES))
        
        logger.info(f"Fetching What's New archive (max {max_pages} pages)...")
        
        for page_num in range(1, max_pages + 1):
            # BIS archive uses pagination (exact URL format may vary)
            # Try common pagination patterns
            separator = '&' if '?' in self.ARCHIVE_URL else '?'
            url = f"{self.ARCHIVE_URL}{separator}page={page_num}"
            
            logger.info(f"Fetching archive page {page_num}...")
            html = self.fetch_page(url)
            
            if not html:
                logger.warning(f"Failed to fetch archive page {page_num}, stopping")
                break
            
            page_entries = self.parse_entries_from_html(html, source_page="archive")
            
            if not page_entries:
                logger.info(f"No entries found on archive page {page_num}, stopping")
                break
            
            entries.extend(page_entries)
            logger.info(f"Found {len(page_entries)} entries on archive page {page_num}")
        
        logger.info(f"Total archive entries fetched: {len(entries)}")
        return entries
    
    def get_all_entries(
        self,
        include_archive: bool = True,
        max_archive_pages: int = MAX_ARCHIVE_PAGES,
    ) -> List[WhatsNewEntry]:
        """
        Fetch all What's New entries
        
        Args:
            include_archive: Whether to include archive entries
            
        Returns:
            List of all WhatsNewEntry objects
        """
        entries = []
        
        # Get main page entries
        entries.extend(self.get_main_page_entries())
        
        # Get archive entries if requested
        if include_archive:
            entries.extend(self.get_archive_entries(max_archive_pages))
        
        # Deduplicate by title
        seen = set()
        unique_entries = []
        for entry in entries:
            if entry.title not in seen:
                seen.add(entry.title)
                unique_entries.append(entry)
        
        logger.info(f"Total unique entries: {len(unique_entries)}")
        return unique_entries
    
    def get_standards_from_whats_new(
        self,
        include_archive: bool = True,
        max_archive_pages: int = MAX_ARCHIVE_PAGES,
    ) -> dict:
        """
        Get all standards mentioned in What's New
        
        Returns dict with format:
        {
            'IS 19497': {
                'titles': [...],
                'latest_date': datetime,
                'count': 3
            },
            ...
        }
        
        Args:
            include_archive: Whether to include archive entries
            
        Returns:
            Dictionary mapping standard IDs to their metadata
        """
        entries = self.get_all_entries(
            include_archive=include_archive,
            max_archive_pages=max_archive_pages,
        )
        return self.summarize_entries(entries)

    @staticmethod
    def summarize_entries(entries: List[WhatsNewEntry]) -> dict:
        standards = {}
        for entry in entries:
            if not entry.standard_id:
                continue
            info = standards.setdefault(entry.standard_id, {
                'titles': [], 'latest_date': entry.published_date, 'count': 0,
            })
            info['titles'].append(entry.title)
            info['count'] += 1
            if entry.published_date and (
                info['latest_date'] is None or entry.published_date > info['latest_date']
            ):
                info['latest_date'] = entry.published_date
        return standards


def fetch_whats_new(include_archive: bool = True, max_archive_pages: int = 1) -> dict:
    """
    Convenience function to fetch What's New standards
    
    Args:
        include_archive: Whether to include archive entries (10 pages)
        
    Returns:
        Dictionary of standards found in What's New
    """
    detector = WhatsNewDetector()
    return detector.get_standards_from_whats_new(
        include_archive=include_archive,
        max_archive_pages=max_archive_pages,
    )


if __name__ == "__main__":
    # Test the module
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    detector = WhatsNewDetector()
    
    print("\n" + "="*60)
    print("Testing What's New Detector")
    print("="*60 + "\n")
    
    # Fetch main page
    print("[1] Fetching main What's New page...")
    main_entries = detector.get_main_page_entries()
    print(f"    Found {len(main_entries)} entries\n")
    
    if main_entries:
        print("    Sample entries:")
        for entry in main_entries[:3]:
            print(f"    - {entry.standard_id or 'Unknown'}: {entry.title[:50]}...")
    
    # Get standards summary
    print("\n[2] Getting standards from What's New...")
    standards = detector.get_standards_from_whats_new(include_archive=False)
    
    if standards:
        print(f"    Found {len(standards)} unique standards")
        print("\n    Top standards mentioned:")
        for std_id, info in sorted(standards.items(), 
                                   key=lambda x: x[1]['count'], 
                                   reverse=True)[:5]:
            print(f"    - {std_id}: {info['count']} mentions (Latest: {info['latest_date']})")
    else:
        print("    No standards found in What's New")
    
    print("\n" + "="*60)
    print("✓ What's New Detector Test Complete")
    print("="*60)
