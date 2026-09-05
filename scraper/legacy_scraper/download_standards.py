# ============================================================
# BIS INDIAN STANDARD PDF AUTOMATION
# ============================================================

import os
import time
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

wait = WebDriverWait(driver, 20)


# ============================================================
# 4. OPEN BIS WEBSITE
# ============================================================

driver.get(BIS_URL)

time.sleep(3)


# ============================================================
# 5. PROCESS EACH STANDARD
# ============================================================

for index, row in df.iterrows():

    # --------------------------------------------------------
    # GET IS NUMBER
    # --------------------------------------------------------

    is_number = str(row["IS_Number"]).strip()

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

        search_tab.send_keys(is_number)

        print(f"Entered: {is_number}")


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

        time.sleep(3)


        # ====================================================
        # STEP 4: CLICK STANDARD RESULT
        # ====================================================

        print("Waiting for standard result...")

        top_standard = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f"//a[@title='{is_number}']"
                )
            )
        )

        print("Standard result found.")

        # Scroll result into view
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            top_standard
        )

        time.sleep(1)


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

        time.sleep(3)


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

        time.sleep(2)


        # ====================================================
        # STEP 6: CLICK DOWNLOAD
        # ====================================================

        print("Waiting for download button...")

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

        time.sleep(5)

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

        time.sleep(2)

        print("BIS search page ready.")


    except Exception as e:

        # ====================================================
        # IF THIS STANDARD FAILS
        # ====================================================

        print(f"\nFAILED: {is_number}")
        print("Error type:", type(e).__name__)
        print("Error:", repr(e))

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

            time.sleep(2)

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