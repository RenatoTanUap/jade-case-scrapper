"""
Jade.io Case Search Scraper - Optimized Version

A GUI application for searching and scraping case links from Jade.io legal database.
Supports court filtering, date ranges, PDF downloads, and pagination.

Author: Optimized version with improved performance and error handling
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    SessionNotCreatedException, TimeoutException,
    NoSuchElementException, WebDriverException
)
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
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

# Configure logging for debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Constants for URL patterns to exclude from results
EXCLUDED_PATTERNS = [
    r"/t/home", r"/t/citator", r"/t/myJade", r"/t/panel",
    r"/t/feedback", r"/t/help", r"#"
]

# Available court options for filtering
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

# Default timeout values
DEFAULT_WAIT_TIME = 5
DEFAULT_PAGE_LOAD_TIMEOUT = 60
MAX_RETRY_ATTEMPTS = 3


@dataclass
class SearchConfig:
    """Configuration class for search parameters"""
    query: str
    court_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    use_and: bool = True
    headless: bool = True
    wait_time: int = DEFAULT_WAIT_TIME
    download_pdfs: bool = False
    download_dir: Optional[str] = None


class JadeScraper:
    """Main scraper class for Jade.io case links"""

    def __init__(self):
        self.driver = None
        self.wait = None

    def get_default_profile_dir(self) -> str:
        """Get the default Chrome profile directory based on OS"""
        home = os.path.expanduser("~")
        system = platform.system()

        profile_paths = {
            'Windows': os.path.join(home, 'AppData', 'Local', 'Google', 'Chrome', 'User Data'),
            'Darwin': os.path.join(home, 'Library', 'Application Support', 'Google', 'Chrome'),
            'Linux': os.path.join(home, '.config', 'google-chrome')
        }

        return profile_paths.get(system, profile_paths['Linux'])

    def format_date_for_jade(self, date_str: str) -> Optional[str]:
        """Convert YYYY-MM-DD format to Jade.io date format"""
        if not date_str:
            return None

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y%m%dT000000000+0800")
        except ValueError as e:
            logging.warning(f"Invalid date format: {date_str} - {e}")
            return None

    def build_search_url(self, config: SearchConfig, page: int = 0) -> str:
        """Build the search URL with all parameters"""
        # Encode search terms
        encoded_terms = [quote_plus(term) for term in config.query.split()]
        query_part = '+AND+'.join(
            encoded_terms) if config.use_and else '+'.join(encoded_terms)

        # Build date filter
        date_part = ""
        if config.start_date and config.end_date:
            since = self.format_date_for_jade(config.start_date)
            until = self.format_date_for_jade(config.end_date)
            if since and until:
                date_part = f":effective.since={since}:effective.until={until}"

        # Build page parameter
        page_part = f"page={page}" if page > 0 else ""

        # Build court filter
        court_part = f":collection.journalGroupName={config.court_name}" if config.court_name else ""

        # Combine all parts
        url = f"https://jade.io/search/{page_part}{court_part}{date_part}:text={query_part}"
        return url

    def setup_driver(self, config: SearchConfig) -> bool:
        """Initialize and configure the Chrome driver"""
        opts = Options()

        # Basic Chrome options
        chrome_options = [
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images'  # Speed up loading
        ]

        for option in chrome_options:
            opts.add_argument(option)

        # Headless mode
        if config.headless:
            opts.add_argument("--headless=new")
        else:
            opts.add_argument("--start-maximized")

        # PDF download configuration
        if config.download_pdfs and config.download_dir:
            prefs = {
                "plugins.always_open_pdf_externally": True,
                "download.prompt_for_download": False,
                "download.default_directory": os.path.abspath(config.download_dir)
            }
            opts.add_experimental_option("prefs", prefs)

        # Try to use existing Chrome profile first
        try:
            user_profile = self.get_default_profile_dir()
            opts.add_argument(f"--user-data-dir={user_profile}")
            self.driver = webdriver.Chrome(options=opts)
        except SessionNotCreatedException:
            # Fallback to fresh Chrome instance
            logging.info("Using fallback Chrome options")
            fallback_opts = Options()
            for option in chrome_options:
                fallback_opts.add_argument(option)

            if config.headless:
                fallback_opts.add_argument('--headless=new')
            else:
                fallback_opts.add_argument("--start-maximized")

            if config.download_pdfs and config.download_dir:
                fallback_opts.add_experimental_option("prefs", prefs)

            self.driver = webdriver.Chrome(options=fallback_opts)

        # Set timeouts
        self.driver.set_page_load_timeout(DEFAULT_PAGE_LOAD_TIMEOUT)
        self.wait = WebDriverWait(self.driver, config.wait_time)
        return True

    def filter_links(self, links: List[str]) -> List[str]:
        """Filter out unwanted links based on excluded patterns"""
        return [link for link in links if link and not any(re.search(pat, link) for pat in EXCLUDED_PATTERNS)]

    def extract_links_from_page(self) -> List[str]:
        """Extract case links from current page"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            raw_links = [
                a.get('href') for a in soup.find_all('a', class_='gwt-Hyperlink alcina-NoHistory')
                if a.get('href')
            ]
            return self.filter_links(raw_links)
        except Exception as e:
            logging.error(f"Error extracting links: {e}")
            return []

    def get_total_pages(self) -> int:
        """Extract total number of pages from search results"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            text = soup.get_text()
            match = re.search(r"You are on page \d+ of (\d+)", text)
            return int(match.group(1)) if match else 1
        except Exception as e:
            logging.error(f"Error getting total pages: {e}")
            return 1

    def download_pdf(self, link: str, config: SearchConfig) -> bool:
        """Download PDF for a single case"""
        full_url = link if link.startswith(
            'http') else f"https://jade.io{link}"

        try:
            self.driver.get(full_url)
            time.sleep(config.wait_time)

            # Wait for and click the Print and Export tab
            tab = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     "//button[@role='tab'][.//img[@title='Print and Export']]")
                )
            )
            tab.click()

            # Wait for and click the PDF download button
            pdf_button = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'a.button-grey.b-pdf'))
            )
            pdf_button.click()
            time.sleep(3)  # Allow time for download to start

            return True

        except (TimeoutException, NoSuchElementException, WebDriverException) as e:
            logging.warning(f"Could not download PDF from {full_url}: {e}")
            return False

    def scrape_case_links(self, config: SearchConfig) -> Tuple[List[str], List[str]]:
        """Main scraping method that returns links and failed downloads"""
        if not self.setup_driver(config):
            return [], ["Failed to initialize browser"]

        all_links = []
        failed_downloads = []
        seen_links: Set[str] = set()

        try:
            # Get first page
            url = self.build_search_url(config)
            self.driver.get(url)
            time.sleep(config.wait_time)

            # Extract links from first page
            links = self.extract_links_from_page()
            all_links.extend(links)
            seen_links.update(links)

            # Get total pages for pagination
            total_pages = self.get_total_pages()
            logging.info(f"Found {total_pages} pages of results")

            # Process remaining pages
            for page in range(1, total_pages):
                try:
                    url = self.build_search_url(config, page)
                    self.driver.get(url)
                    time.sleep(config.wait_time)

                    links = self.extract_links_from_page()
                    new_links = [
                        link for link in links if link not in seen_links]

                    if not new_links:
                        logging.info(
                            f"No new links found on page {page + 1}, stopping pagination")
                        break

                    all_links.extend(new_links)
                    seen_links.update(new_links)

                    logging.info(
                        f"Processed page {page + 1}/{total_pages}, found {len(new_links)} new links")

                except Exception as e:
                    logging.warning(f"Error processing page {page + 1}: {e}")
                    break

            # Download PDFs if requested
            if config.download_pdfs and config.download_dir:
                logging.info(
                    f"Starting PDF downloads for {len(all_links)} links")
                for i, link in enumerate(all_links, 1):
                    if not self.download_pdf(link, config):
                        failed_downloads.append(
                            f"Failed to download from: {link}")

                    if i % 10 == 0:  # Log progress every 10 downloads
                        logging.info(f"Downloaded {i}/{len(all_links)} PDFs")

        except TimeoutException:
            return [], ["Page timed out"]
        except Exception as e:
            logging.error(f"Unexpected error during scraping: {e}")
            return [], ["Scraper stopped abruptly"]
        finally:
            self.cleanup()

        # Convert relative links to absolute URLs
        absolute_links = [
            link if link.startswith('http') else f"https://jade.io{link}"
            for link in all_links
        ]

        return absolute_links, failed_downloads

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logging.error(f"Error closing driver: {e}")
            finally:
                self.driver = None
                self.wait = None


class JadeScraperGUI:
    """GUI class for the Jade scraper application"""

    def __init__(self):
        self.root = tk.Tk()
        self.scraper = JadeScraper()
        self.setup_ui()

    def setup_ui(self):
        """Initialize the user interface"""
        self.root.title("Jade.io Case Search - Optimized")
        self.root.geometry("900x700")

        # Main frame
        self.frame = ttk.Frame(self.root, padding=10)
        self.frame.grid(row=0, column=0, sticky="nsew")

        # Configure grid weights for responsive design
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)

        self.create_input_widgets()
        self.create_output_widgets()
        self.create_status_widgets()

    def create_input_widgets(self):
        """Create input widgets for search parameters"""
        row = 0

        # Search query input
        ttk.Label(self.frame, text="Enter Search Query:").grid(
            row=row, column=0, sticky="w", pady=2)
        self.query_entry = ttk.Entry(self.frame, width=60)
        self.query_entry.grid(
            row=row, column=1, columnspan=2, pady=2, sticky="ew")
        row += 1

        # Checkboxes row 1
        self.use_and_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.frame, text="Use AND between terms",
                        variable=self.use_and_var).grid(row=row, column=0, sticky="w", pady=2)

        self.headless_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.frame, text="Run in Headless Mode",
                        variable=self.headless_var).grid(row=row, column=1, sticky="w", pady=2)

        self.download_var = tk.BooleanVar()
        ttk.Checkbutton(self.frame, text="Download PDFs",
                        variable=self.download_var).grid(row=row, column=2, sticky="w", pady=2)
        row += 1

        # Download folder selection
        ttk.Label(self.frame, text="Download Folder:").grid(
            row=row, column=0, sticky="w", pady=2)
        self.download_dir_var = tk.StringVar()
        ttk.Entry(self.frame, textvariable=self.download_dir_var,
                  width=45).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(self.frame, text="Browse...",
                   command=self.browse_folder).grid(row=row, column=2, padx=5, pady=2)
        row += 1

        # Court filter
        self.use_court_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.frame, text="Filter by Court",
                        variable=self.use_court_var).grid(row=row, column=0, sticky="w", pady=2)

        self.court_var = tk.StringVar()
        self.court_dropdown = ttk.Combobox(self.frame, textvariable=self.court_var,
                                           values=COURTS, width=58, state="readonly")
        self.court_dropdown.grid(
            row=row, column=1, columnspan=2, pady=2, sticky="ew")
        self.court_dropdown.set("All Courts")
        row += 1

        # Date filters
        date_frame = ttk.Frame(self.frame)
        date_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=5)

        ttk.Label(date_frame, text="Start Date (YYYY-MM-DD):").grid(row=0,
                                                                    column=0, sticky="w", padx=5)
        self.start_date_var = tk.StringVar()
        ttk.Entry(date_frame, textvariable=self.start_date_var,
                  width=15).grid(row=0, column=1, padx=5)

        ttk.Label(date_frame, text="End Date (YYYY-MM-DD):").grid(row=0,
                                                                  column=2, sticky="w", padx=5)
        self.end_date_var = tk.StringVar()
        ttk.Entry(date_frame, textvariable=self.end_date_var,
                  width=15).grid(row=0, column=3, padx=5)

        ttk.Label(date_frame, text="Wait Time (seconds):").grid(
            row=0, column=4, sticky="w", padx=5)
        self.wait_time_var = tk.StringVar(value="5")
        ttk.Entry(date_frame, textvariable=self.wait_time_var,
                  width=10).grid(row=0, column=5, padx=5)
        row += 1

        # Search button
        self.search_button = ttk.Button(
            self.frame, text="Search", command=self.run_scraper)
        self.search_button.grid(row=row, column=1, pady=10)
        row += 1

        self.current_row = row

    def create_output_widgets(self):
        """Create output text area"""
        ttk.Label(self.frame, text="Results:").grid(
            row=self.current_row, column=0, sticky="w", pady=2)
        self.current_row += 1

        self.output_box = scrolledtext.ScrolledText(
            self.frame, wrap=tk.WORD, width=80, height=20)
        self.output_box.grid(row=self.current_row, column=0,
                             columnspan=3, pady=5, sticky="nsew")
        self.frame.rowconfigure(self.current_row, weight=1)
        self.current_row += 1

    def create_status_widgets(self):
        """Create status and progress widgets"""
        status_frame = ttk.Frame(self.frame)
        status_frame.grid(row=self.current_row, column=0,
                          columnspan=3, sticky="ew", pady=5)
        status_frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(status_frame, text="Ready")
        self.status_label.grid(row=0, column=0, sticky="w")

        self.progress_bar = ttk.Progressbar(status_frame, mode='indeterminate')
        self.progress_bar.grid(row=0, column=1, sticky="e", padx=10)

    def browse_folder(self):
        """Open folder selection dialog"""
        folder = filedialog.askdirectory()
        if folder:
            self.download_dir_var.set(folder)

    def validate_inputs(self, config: SearchConfig) -> bool:
        """Validate user inputs before starting scraper"""
        if not config.query.strip():
            messagebox.showerror("Input Error", "Please enter a search query.")
            return False

        if config.download_pdfs and not config.download_dir:
            messagebox.showerror(
                "Input Error", "Please select a folder to download PDFs.")
            return False

        # Validate date format if provided
        if config.start_date:
            try:
                datetime.strptime(config.start_date, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror(
                    "Input Error", "Start date must be in YYYY-MM-DD format.")
                return False

        if config.end_date:
            try:
                datetime.strptime(config.end_date, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror(
                    "Input Error", "End date must be in YYYY-MM-DD format.")
                return False

        return True

    def get_search_config(self) -> SearchConfig:
        """Create SearchConfig from GUI inputs"""
        try:
            wait_time = int(self.wait_time_var.get().strip()) if self.wait_time_var.get(
            ).strip().isdigit() else DEFAULT_WAIT_TIME
        except ValueError:
            wait_time = DEFAULT_WAIT_TIME

        return SearchConfig(
            query=self.query_entry.get().strip(),
            court_name=self.court_var.get() if self.use_court_var.get(
            ) and self.court_var.get() != "All Courts" else None,
            start_date=self.start_date_var.get().strip() or None,
            end_date=self.end_date_var.get().strip() or None,
            use_and=self.use_and_var.get(),
            headless=self.headless_var.get(),
            wait_time=wait_time,
            download_pdfs=self.download_var.get(),
            download_dir=self.download_dir_var.get().strip() or None
        )

    def run_scraper(self):
        """Start the scraping process in a separate thread"""
        def scraper_task():
            config = self.get_search_config()

            try:
                # Run the scraper
                links, failed_downloads = self.scraper.scrape_case_links(
                    config)

                # Update UI with results
                self.output_box.delete("1.0", tk.END)

                if not links and not failed_downloads:
                    self.output_box.insert(tk.END,
                                           "No links found. Try increasing the wait time or checking your search terms.")
                elif failed_downloads and "Page timed out" in failed_downloads:
                    self.output_box.insert(tk.END,
                                           "Scraper stopped. Page took too long to load (60 seconds max).")
                elif failed_downloads and "Scraper stopped abruptly" in failed_downloads:
                    self.output_box.insert(tk.END,
                                           "Scraper stopped abruptly (browser may have been closed).")
                else:
                    # Display successful links
                    if links:
                        self.output_box.insert(
                            tk.END, f"Found {len(links)} case links:\n\n")
                        for i, link in enumerate(links, 1):
                            self.output_box.insert(tk.END, f"{i}. {link}\n")

                    # Display failed downloads if any
                    if failed_downloads:
                        self.output_box.insert(
                            tk.END, f"\n\nFailed Downloads ({len(failed_downloads)}):\n")
                        for failure in failed_downloads:
                            self.output_box.insert(tk.END, f"• {failure}\n")

            except Exception as e:
                messagebox.showerror(
                    "Error", f"An unexpected error occurred: {str(e)}")
                logging.error(f"Scraper error: {e}")
            finally:
                # Reset UI state
                self.progress_bar.stop()
                self.status_label.config(text="Done")
                self.search_button.config(state="normal")

        # Validate inputs
        config = self.get_search_config()
        if not self.validate_inputs(config):
            return

        # Update UI state
        self.output_box.delete("1.0", tk.END)
        self.status_label.config(text="Scraping in progress...")
        self.progress_bar.start()
        self.search_button.config(state="disabled")

        # Start scraper in background thread
        threading.Thread(target=scraper_task, daemon=True).start()

    def run(self):
        """Start the GUI application"""
        self.root.mainloop()


def main():
    """Main entry point"""
    app = JadeScraperGUI()
    app.run()


if __name__ == "__main__":
    main()
