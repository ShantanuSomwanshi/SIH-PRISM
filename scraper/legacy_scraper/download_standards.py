# ============================================================
# BIS INDIAN STANDARD PDF AUTOMATION
# ============================================================

import os
import re
import time
import json
from urllib.parse import parse_qs, unquote, urlparse
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# 1. SETTINGS
# ============================================================

# Excel file containing IS numbers
EXCEL_FILE = "Book 2.xlsx"

# Folder where downloaded files will be stored
DOWNLOAD_FOLDER = os.path.abspath("downloads")

# BIS website
BIS_URL = "https://standards.bis.gov.in/website/know-your-standards"


# Create downloads folder
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


# ============================================================
# 2. READ EXCEL FILE
# ============================================================

df = pd.read_excel(EXCEL_FILE)
WAIT_SECONDS = int(os.getenv("BIS_WAIT_SECONDS", "10"))
DOWNLOAD_SECONDS = int(os.getenv("BIS_DOWNLOAD_SECONDS", "30"))

print("Total standards:", len(df))


# ============================================================
# 3. SET UP CHROME
# ============================================================

chrome_options = webdriver.ChromeOptions()

chrome_options.add_experimental_option(
    "prefs",
    {
        "download.default_directory": DOWNLOAD_FOLDER,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True
    }
)

driver = webdriver.Chrome(options=chrome_options)

wait = WebDriverWait(driver, WAIT_SECONDS)


# ============================================================
# 4. OPEN BIS WEBSITE
# ============================================================

driver.get(BIS_URL)
wait.until(EC.presence_of_element_located((By.ID, "isSearch")))


# ============================================================
# 5. PROCESS EACH STANDARD
# ============================================================

for index, row in df.iterrows():

    # --------------------------------------------------------
    # GET IS NUMBER
    # --------------------------------------------------------

    is_number = str(row["IS_Number"]).strip()
    standard_number_match = re.search(r"\d{1,6}", is_number)
    standard_number = standard_number_match.group(0) if standard_number_match else is_number

    print("\n======================================")
    print(f"Processing {index + 1}/{len(df)}")
    print(f"IS Number: {is_number}")
    print("======================================")


    try:

        # ====================================================
        # STEP 1: CLICK SEARCH TAB
        # ====================================================

        print("Waiting for search tab...")

        search_tab = wait.until(
            EC.element_to_be_clickable(
                (By.ID, "isSearch")
            )
        )

        print("Search tab found.")

        search_tab.click()


        # ====================================================
        # STEP 2: ENTER IS NUMBER
        # ====================================================

        print("Entering IS number...")

        search_tab.clear()

        search_tab.send_keys(standard_number)

        print(f"Entered search value: {standard_number} (selected ID: {is_number})")


        # ====================================================
        # STEP 3: CLICK SEARCH BUTTON
        # ====================================================

        print("Waiting for search button...")

        search_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Search']")
            )
        )

        print("Search button found.")

        search_button.click()

        print("Search clicked.")

        wait.until(EC.presence_of_element_located((By.XPATH, "//a[@title]")))


        # ====================================================
        # STEP 4: CLICK STANDARD RESULT
        # ====================================================

        print("Waiting for standard result...")

        top_standard = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f"//a[@title='{is_number}'] | //a[contains(@title, '{standard_number}')] | //*[@title and contains(@title, '{standard_number}')]"
                )
            )
        )

        print("Standard result found.")
        result_title = top_standard.get_attribute("title") or is_number
        result_text = top_standard.text or result_title
        result_href = top_standard.get_attribute("href") or ""
        print("Matched result:", {
            "title": result_title,
            "text": result_text,
            "href": result_href,
        })

        # Scroll result into view
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            top_standard
        )

        # Try normal click
        try:

            top_standard.click()

        except Exception:

            # If overlay blocks click, use JavaScript
            driver.execute_script(
                "arguments[0].click();",
                top_standard
            )

        print("Standard selected.")

        detail_url = result_href or driver.current_url
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[@title='Download PDF']")))
        detail_text = " ".join(driver.find_element(By.TAG_NAME, "body").text.split())
        standard_id = unquote(parse_qs(urlparse(detail_url).query).get("standardNumber", [is_number])[0])
        current_artifact = {
            "standard_id": standard_id,
            "title": is_number,
            "status": "UNKNOWN",
            "source_url": detail_url,
            "raw_text_excerpt": detail_text[:5000],
        }
        artifact_path = os.path.join(DOWNLOAD_FOLDER, f"bis_standard_{index + 1}.json")
        with open(artifact_path, "w", encoding="utf-8") as artifact_file:
            json.dump(current_artifact, artifact_file, ensure_ascii=False, indent=2)
        print(f"Current BIS detail captured: {artifact_path}")

        driver.get(BIS_URL)
        wait.until(EC.presence_of_element_located((By.ID, "isSearch")))
        print("BIS search page ready.")
        continue

        # ====================================================
        # STEP 5: CLICK COMPOSITION
        # ====================================================

        print("Waiting for composition...")

        composition_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[@title='Composition']")
            )
        )

        print("Composition found.")

        composition_button.click()

        print("Composition clicked.")

        # ====================================================
        # STEP 6: CLICK DOWNLOAD
        # ====================================================

        print("Waiting for download button...")

        before_download = set(os.listdir(DOWNLOAD_FOLDER))
        download_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Download Excel']")
            )
        )

        print("Download button found.")

        download_button.click()

        print("Download clicked.")


        # ====================================================
        # STEP 7: WAIT FOR DOWNLOAD
        # ====================================================

        deadline = time.time() + DOWNLOAD_SECONDS
        while time.time() < deadline:
            temporary_downloads = [name for name in os.listdir(DOWNLOAD_FOLDER) if name.endswith('.crdownload')]
            current_downloads = set(os.listdir(DOWNLOAD_FOLDER))
            new_downloads = current_downloads - before_download
            if new_downloads and not temporary_downloads:
                break
            time.sleep(0.25)

        print(f"Completed: {is_number}")


        # ====================================================
        # STEP 8: RETURN TO INITIAL BIS PAGE
        # ====================================================

        print("Returning to BIS search page...")

        driver.get(BIS_URL)

        # Wait until the search field is available again
        wait.until(
            EC.presence_of_element_located(
                (By.ID, "isSearch")
            )
        )

        print("BIS search page ready.")


    except Exception as e:

        # ====================================================
        # IF THIS STANDARD FAILS
        # ====================================================

        print(f"\nFAILED: {is_number}")
        print("Error type:", type(e).__name__)
        print("Error:", repr(e))
        try:
            visible_text = " ".join(driver.find_element(By.TAG_NAME, "body").text.split())
            print("BIS page response:", visible_text[:1000])
            titled = [element.get_attribute("title") for element in driver.find_elements(By.XPATH, "//*[@title]")]
            print("BIS titled elements:", [title for title in titled if title][:30])
        except Exception as diagnostic_error:
            print("Could not collect BIS response diagnostics:", repr(diagnostic_error))

        # ----------------------------------------------------
        # IMPORTANT:
        # Even after a failure, return to the initial page
        # before processing the next standard.
        # ----------------------------------------------------

        try:

            print("Resetting BIS page after failure...")

            driver.get(BIS_URL)

            wait.until(
                EC.presence_of_element_located(
                    (By.ID, "isSearch")
                )
            )

            print("BIS page reset successfully.")

        except Exception as reset_error:

            print("Could not reset BIS page.")
            print(
                "Reset error:",
                type(reset_error).__name__,
                repr(reset_error)
            )

        # ----------------------------------------------------
        # DO NOT STOP THE PROGRAM
        # Move to next standard
        # ----------------------------------------------------

        continue


# ============================================================
# 6. CLOSE BROWSER
# ============================================================

driver.quit()


print("\n======================================")
print("ALL STANDARDS PROCESSED")
print("======================================")