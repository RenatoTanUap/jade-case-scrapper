import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import SessionNotCreatedException, TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import platform
import os
import re
import time
import logging
import threading
from datetime import datetime

logging.basicConfig(level=logging.INFO)

EXCLUDED_PATTERNS = [
    r"/t/home", r"/t/citator", r"/t/myJade", r"/t/panel",
    r"/t/feedback", r"/t/help", r"#"
]

COURTS = [
    "All Courts",
    "All Legislation",
    "HIGH COURT",
    "All High Court",
    "High Court of Australia (HCA)",
    "High Court of Australia Single Justice Judgments (HCASJ)",
    "Privy Council - Appeals from the High Court of Australia (UKPCHCA)",
    "High Court of Australia - Bulletins (HCAB)",
    "High Court of Australia - Dispositions (HCADisp)",
    "High Court of Australia - Special Leave Dispositions (HCASL)",
    "High Court of Australia - Transcripts (HCATrans)",
    "COMMONWEALTH - INTERMEDIATE APPELLATE COURTS",
    "All Commonwealth - Intermediate Appellate Courts",
    "Federal Court of Australia - Full Court (FCAFC)",
    "Family Court of Australia - Full Court (FamCAFC)",
    "Federal Circuit and Family Court of Australia - Division 1 Appellate Jurisdiction (FedCFamC1A)"
]


def get_default_profile_dir():
    home = os.path.expanduser("~")
    system = platform.system()
    if system == 'Windows':
        return os.path.join(home, 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
    elif system == 'Darwin':
        return os.path.join(home, 'Library', 'Application Support', 'Google', 'Chrome')
    else:
        return os.path.join(home, '.config', 'google-chrome')


def format_date_for_jade(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y%m%dT000000000+0800")
    except ValueError:
        return None


def build_search_url(query, court_name=None, start_date=None, end_date=None, use_and=True):
    encoded_terms = [quote_plus(term) for term in query.split()]
    query_part = '+AND+'.join(encoded_terms) if use_and else '+'.join(encoded_terms)
    date_part = ""

    if start_date and end_date:
        since = format_date_for_jade(start_date)
        until = format_date_for_jade(end_date)
        if since and until:
            date_part = f":effective.since={since}:effective.until={until}"

    if court_name:
        return f"https://jade.io/search/collection.journalGroupName={court_name}{date_part}:text={query_part}"
    return f"https://jade.io/search/{date_part}:text={query_part}"


def build_paginated_url(query, page, court_name=None, start_date=None, end_date=None, use_and=True):
    encoded_terms = [quote_plus(term) for term in query.split()]
    query_part = '+AND+'.join(encoded_terms) if use_and else '+'.join(encoded_terms)
    date_part = ""

    if start_date and end_date:
        since = format_date_for_jade(start_date)
        until = format_date_for_jade(end_date)
        if since and until:
            date_part = f":effective.since={since}:effective.until={until}"

    if court_name:
        return f"https://jade.io/search/page={page}:collection.journalGroupName={court_name}{date_part}:text={query_part}"
    return f"https://jade.io/search/page={page}{date_part}:text={query_part}"


def filter_links(links):
    return [link for link in links if not any(re.search(pat, link) for pat in EXCLUDED_PATTERNS)]


def scrape_case_links(query, headless=True, wait_time=5, page_load_timeout=60, download_pdfs=False, download_dir=None, court_name=None, start_date=None, end_date=None, use_and=True):
    opts = Options()
    user_profile = get_default_profile_dir()
    opts.add_argument(f"--user-data-dir={user_profile}")

    if headless:
        opts.add_argument("--headless=new")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument('--disable-gpu')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')

    failed_downloads = []

    if download_pdfs and download_dir:
        prefs = {
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False,
            "download.default_directory": os.path.abspath(download_dir)
        }
        opts.add_experimental_option("prefs", prefs)

    try:
        driver = webdriver.Chrome(options=opts)
    except SessionNotCreatedException:
        fallback_opts = Options()
        if headless:
            fallback_opts.add_argument('--headless=new')
        else:
            fallback_opts.add_argument("--start-maximized")
        fallback_opts.add_argument('--disable-gpu')
        fallback_opts.add_argument('--no-sandbox')
        fallback_opts.add_argument('--disable-dev-shm-usage')
        if download_pdfs and download_dir:
            fallback_opts.add_experimental_option("prefs", prefs)
        driver = webdriver.Chrome(options=fallback_opts)

    driver.set_page_load_timeout(page_load_timeout)
    links = []
    try:
        driver.get(build_search_url(query, court_name,
                   start_date, end_date, use_and))
        time.sleep(wait_time)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        raw_links = [a.get('href') for a in soup.find_all(
            'a', class_='gwt-Hyperlink alcina-NoHistory') if a.get('href')]
        filtered = filter_links(raw_links)
        links.extend(filtered)

        seen_links = set(filtered)
        p = 1
        while True:
            try:
                driver.get(build_paginated_url(
                    query, p, court_name, start_date, end_date, use_and))
                time.sleep(wait_time)
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                raw_links = [a.get('href') for a in soup.find_all(
                    'a', class_='gwt-Hyperlink alcina-NoHistory') if a.get('href')]
                filtered = filter_links(raw_links)
                new_links = [l for l in filtered if l not in seen_links]
                if not new_links:
                    break
                seen_links.update(new_links)
                links.extend(new_links)
            except Exception:
                logging.warning(
                    f"Stopping pagination at page {p} due to error.")
                break

        if download_pdfs and download_dir:
            for link in links:
                full_url = link if link.startswith(
                    'http') else f"https://jade.io{link}"
                try:
                    driver.get(full_url)
                    time.sleep(wait_time)
                    tab = driver.find_element(
                        By.XPATH, "//button[@role='tab'][.//img[@title='Print and Export']]")
                    tab.click()
                    time.sleep(1)
                    pdf_button = driver.find_element(
                        By.CSS_SELECTOR, 'a.button-grey.b-pdf')
                    pdf_button.click()
                    time.sleep(3)
                except (TimeoutException, NoSuchElementException, WebDriverException):
                    logging.warning(f"Could not process: {full_url}")
                    failed_downloads.append(
                        f"Failed to download from: {full_url}")
                    continue
    except Exception:
        logging.warning(
            "Browser closed unexpectedly. Scraper stopped abruptly.")
        return ["Scraper stopped abruptly."]
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return [f"https://jade.io{link}" for link in links] + failed_downloads


def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        download_dir_var.set(folder)


def run_scraper():
    def task():
        use_and = use_and_var.get()
        try:
            wait_time_str = wait_time_var.get().strip()
            wait_time = int(wait_time_str) if wait_time_str.isdigit() else 5
            court_name = court_var.get() if use_court_var.get() else None
            results = scrape_case_links(
                query,
                headless=headless,
                wait_time=wait_time,
                download_pdfs=download_pdfs,
                download_dir=download_dir,
                court_name=court_name,
                start_date=start_date,
                end_date=end_date,
                use_and=use_and
            )
            output_box.delete("1.0", tk.END)
            if not results:
                output_box.insert(tk.END, "No links found.")
            elif results == ["Scraper stopped abruptly."]:
                output_box.insert(
                    tk.END, "Scraper stopped abruptly (browser may have been closed).")
            else:
                for link in results:
                    output_box.insert(tk.END, f"{link}\n")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            progress_bar.stop()
            status_label.config(text="Done.")
            search_button.config(state="normal")

    query = query_entry.get().strip()
    headless = headless_var.get()
    download_pdfs = download_var.get()
    download_dir = download_dir_var.get()
    start_date = start_date_var.get().strip()
    end_date = end_date_var.get().strip()

    if not query:
        messagebox.showerror("Input Error", "Please enter a search query.")
        return
    if download_pdfs and not download_dir:
        messagebox.showerror(
            "Input Error", "Please select a folder to download PDFs.")
        return

    output_box.delete("1.0", tk.END)
    status_label.config(text="Scraping in progress...")
    progress_bar.start()
    search_button.config(state="disabled")
    threading.Thread(target=task, daemon=True).start()


root = tk.Tk()
root.title("Jade.io Case Search")
frame = ttk.Frame(root, padding=10)
frame.grid(row=0, column=0, sticky="nsew")

# Query Input
ttk.Label(frame, text="Enter Search Query:").grid(row=0, column=0, sticky="w")
query_entry = ttk.Entry(frame, width=60)
query_entry.grid(row=0, column=1, columnspan=2, pady=5)


# Use AND Between Terms
use_and_var = tk.BooleanVar(value=True)
ttk.Checkbutton(frame, text="Use AND between terms",
                variable=use_and_var).grid(row=1, column=2, sticky="w")
# Headless Mode
headless_var = tk.BooleanVar(value=True)
ttk.Checkbutton(frame, text="Run in Headless Mode",
                variable=headless_var).grid(row=1, column=1, sticky="w")

# Download Option
download_var = tk.BooleanVar()
ttk.Checkbutton(frame, text="Download PDFs", variable=download_var).grid(
    row=2, column=1, sticky="w")

download_dir_var = tk.StringVar()
ttk.Label(frame, text="Download Folder:").grid(row=3, column=0, sticky="w")
ttk.Entry(frame, textvariable=download_dir_var,
          width=45).grid(row=3, column=1, sticky="w")
ttk.Button(frame, text="Browse...", command=browse_folder).grid(
    row=3, column=2, padx=5, pady=5)

# Court Filter
use_court_var = tk.BooleanVar(value=True)
ttk.Checkbutton(frame, text="Filter by Court", variable=use_court_var).grid(
    row=4, column=0, sticky="w")

court_var = tk.StringVar()
court_dropdown = ttk.Combobox(
    frame, textvariable=court_var, values=COURTS, width=58)
court_dropdown.grid(row=4, column=1, columnspan=2, pady=5)
court_dropdown.set("All Courts")

# Date Filters
ttk.Label(frame, text="Start Date (YYYY-MM-DD):").grid(row=5,
                                                       column=0, sticky="w")
start_date_var = tk.StringVar()
ttk.Entry(frame, textvariable=start_date_var,
          width=20).grid(row=5, column=1, sticky="w")

ttk.Label(frame, text="End Date (YYYY-MM-DD):").grid(row=6, column=0, sticky="w")
end_date_var = tk.StringVar()
ttk.Entry(frame, textvariable=end_date_var, width=20).grid(
    row=6, column=1, sticky="w")

# Search Button
search_button = ttk.Button(frame, text="Search", command=run_scraper)
search_button.grid(row=7, column=1, pady=5, sticky="e")

# Wait Time Input
ttk.Label(frame, text="Wait Time (seconds):").grid(row=7, column=0, sticky="w")
wait_time_var = tk.StringVar()
ttk.Entry(frame, textvariable=wait_time_var, width=10).grid(
    row=7, column=1, sticky="w")
wait_time_var.set("5")


# Output Box
output_box = scrolledtext.ScrolledText(
    frame, wrap=tk.WORD, width=80, height=20)
output_box.grid(row=8, column=0, columnspan=3, pady=10)

# Status and Progress
status_label = ttk.Label(frame, text="")
status_label.grid(row=9, column=0, sticky="w", columnspan=2)
progress_bar = ttk.Progressbar(frame, mode='indeterminate')
progress_bar.grid(row=9, column=2, sticky="e")

root.mainloop()
