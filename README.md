# Jade Case Scraper

A Python-based tool for scraping case data from Jade legal databases.

## Setup

### Prerequisites

- Python 3.x installed on your system

### Installation

1. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd jade-case-scrapper
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**

   **Windows:**

   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

   **macOS/Linux:**

   ```bash
   source venv/bin/activate
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the scraper with:

```bash
python "Jade Case Scraper.py"
```

## Building an Executable

To create a standalone executable file in Windows:

1. **Install PyInstaller**

   ```bash
   pip install pyinstaller
   ```

2. **Build the executable**
   ```bash
   pyinstaller --noconfirm --onefile --windowed "Jade Case Scraper.py"
   ```

The executable will be created in the `dist/` directory.
