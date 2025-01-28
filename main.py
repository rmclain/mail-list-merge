import pandas as pd
import re
import pgeocode
from tqdm import tqdm
import usaddress
from nameparser import HumanName
import glob

def combine_csv_files(input_files, output_file, combined_file):
    dataframes = []
    for file in input_files:
        df = pd.read_csv(file, header=0)
        dataframes.append(df)
    
    combined_df = pd.concat(dataframes, ignore_index=True)
    combined_df.columns = ['name', 'address', 'address2', 'city', 'st', 'zip']
    combined_df.drop([0], axis=0, inplace=True)
    
    # Save the initial combined CSV
    combined_df.to_csv(output_file, index=False)
    
    # Record the total number of records before removing duplicates
    total_records = len(combined_df)
    
    # Normalize names by removing middle initials and using nameparser
    def normalize_name(name):
        parsed_name = HumanName(name)
        # Remove middle name/initial
        parsed_name.middle = ''
        return f"{parsed_name.first} {parsed_name.last}".strip().lower()
    
    # Apply tqdm to the name normalization process
    combined_df['name'] = combined_df['name'].progress_apply(normalize_name)
    
    # Preprocess addresses to standardize common abbreviations
    def preprocess_address(address):
        if pd.isna(address):
            return address
        address = address.lower()
        # Replace abbreviations (e.g., 'Ct' -> 'Court')
        address = re.sub(r'\bct\b', 'court', address)
        address = re.sub(r'\bst\b', 'street', address)
        address = re.sub(r'\bave\b', 'avenue', address)
        address = re.sub(r'\bdr\b', 'drive', address)
        address = re.sub(r'\brd\b', 'road', address)
        return address

    # Apply tqdm to the address preprocessing
    combined_df['address'] = combined_df['address'].progress_apply(preprocess_address)
    
    # Normalize addresses using usaddress
    def normalize_address(address):
        if pd.isna(address):
            return address
        try:
            parsed_address = usaddress.tag(str(address))
            return ' '.join(parsed_address[0].values()).lower()
        except usaddress.RepeatedLabelError:
            return address.lower()
    
    # Apply tqdm to the address normalization
    combined_df['address'] = combined_df['address'].progress_apply(normalize_address)
    
    # Remove duplicates based on normalized 'name' and 'address'
    combined_df.drop_duplicates(subset=['name', 'address'], inplace=True)
    
    # Calculate the number of duplicate records
    records_after_duplicates = len(combined_df)
    duplicates_removed = total_records - records_after_duplicates
    
    # Drop records without an address or zip code
    records_before_dropna = len(combined_df)
    combined_df.dropna(subset=['address', 'zip'], inplace=True)
    records_dropped_due_to_na = records_before_dropna - len(combined_df)
    
    # Format zip codes
    def format_zip(zip_code):
        zip_code = str(zip_code).split('.')[0]  # Remove any decimal point
        zip_code = re.sub(r'-.*', '', zip_code)  # Remove anything after a dash
        return zip_code.zfill(5)  # Pad with leading zeros to ensure 5 digits
    
    combined_df['zip'] = combined_df['zip'].apply(format_zip)
    
    # Sort by zip code
    combined_df.sort_values(by='zip', inplace=True)
    
    # Use pgeocode to fill in the city and state based on zip code
    nomi = pgeocode.Nominatim('us')
    def get_city_state(zip_code):
        location = nomi.query_postal_code(zip_code)
        if location is not None and pd.notna(location.state_code):
            return location.place_name, location.state_code
        return None, None
    
    # Apply tqdm to the city and state filling process
    combined_df[['city', 'st']] = combined_df['zip'].progress_apply(lambda z: pd.Series(get_city_state(z)))
    
    # Drop records where state is not set
    records_before_state_drop = len(combined_df)
    combined_df.dropna(subset=['st'], inplace=True)
    records_dropped_due_to_no_state = records_before_state_drop - len(combined_df)
    
    # Convert 'name' and 'address' back to Title case
    combined_df['name'] = combined_df['name'].str.title()
    combined_df['address'] = combined_df['address'].str.title()
    
    # Save the final combined CSV without duplicates
    combined_df.to_csv(combined_file, index=False)
    
    # Print statistics
    print(f"Total records before removing duplicates: {total_records}")
    print(f"Total records after removing duplicates: {len(combined_df)}")
    print(f"Number of duplicate records removed: {duplicates_removed}")
    print(f"Number of records dropped due to missing address or zip: {records_dropped_due_to_na}")
    print(f"Number of records dropped due to missing state: {records_dropped_due_to_no_state}")

# Initialize tqdm for pandas
tqdm.pandas()

# Get all CSV files from the inputs directory
input_files = glob.glob('inputs/*.csv')
combine_csv_files(input_files, 'output.csv', 'combined.csv')
