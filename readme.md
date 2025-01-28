# Mail List Merge

This repository provides a tool to combine multiple CSV files into a single, processed CSV file. The tool normalizes names and addresses, removes duplicates, and fills in missing city and state information based on zip codes.

## How to Use

1. **Add CSV Files**: Place your CSV files in the `inputs` directory. Each CSV file should have the following column headers:

   - `name`
   - `address`
   - `address2`
   - `city`
   - `st`
   - `zip`

2. **Run the Script**: Execute the script to process the CSV files. The script will:

   - Combine all CSV files in the `inputs` directory.
   - Normalize names and addresses.
   - Remove duplicate entries.
   - Fill in missing city and state information using zip codes.
   - Save the processed data to `combined.csv`.

3. **Output**: The processed CSV file will be saved as `combined.csv` in the root directory.

## Requirements

Ensure you have the following Python packages installed:

- `pandas`
- `pgeocode`
- `tqdm`
- `usaddress`
- `nameparser`

You can install these packages using the following command:

```bash
pip install -r requirements.txt
```

## Code Overview

The main functionality is implemented in `main.py`, which includes:

- Reading and combining CSV files.
- Normalizing and preprocessing data.
- Removing duplicates and handling missing data.
- Saving the final processed CSV file.

For more details, refer to the code in `main.py`.

## Notes

- Ensure your CSV files are correctly formatted with the specified headers.
- The script uses `pgeocode` to fill in city and state information based on zip codes, so an internet connection is required for this feature.

Happy processing!
