import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from bs4 import BeautifulSoup
import time
import os


DATA_PATH = "data_files/data_files/diabetic_data.csv"
MAPPING_PATH = "data_files/data_files/IDs_mapping.csv"
PLOTS_DIR = "plots"

os.makedirs(PLOTS_DIR, exist_ok=True)

def parse_ids_mapping(path):
    """
    Parses the non-standard IDs_mapping.csv file into three dictionaries.
    """
    mappings = {
        'admission_type_id': {},
        'discharge_disposition_id': {},
        'admission_source_id': {}
    }
    
    current_section = None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('admission_type_id'):
                current_section = 'admission_type_id'
                continue
            elif line.startswith('discharge_disposition_id'):
                current_section = 'discharge_disposition_id'
                continue
            elif line.startswith('admission_source_id'):
                current_section = 'admission_source_id'
                continue
                
            if ',' in line:
                parts = line.split(',', 1)
                if len(parts) == 2:
                    try:
                        key = int(parts[0])
                        val = parts[1].strip().replace('"', '')
                        if current_section:
                            mappings[current_section][key] = val
                    except ValueError:
                        continue
                        
        print("Successfully parsed ID mappings.")
        return mappings
    except Exception as e:
        print(f"Error parsing mapping file: {e}")
        return None

def phase_1_sanitation():
    print("\n--- PHASE 1: DATA INGESTION & SANITATION ---")
    
    print("Loading dataset...")
    df = pd.read_csv(DATA_PATH, na_values=['?'])
    print(f"Initial Shape: {df.shape}")
    
    print("\n--- AUDIT: HEAD ---")
    print(df.head())
    print("\n--- AUDIT: INFO ---")
    print(df.info())
    print("\n--- AUDIT: DESCRIBE ---")
    print(df.describe())
    print("\n--- AUDIT: COLUMNS ---")
    print(df.columns)
    
    
    # 2. Audit Missingness
    missing_percent = df.isnull().mean() * 100
    print("\nTop 5 Columns by Missingness:")
    print(missing_percent.sort_values(ascending=False).head())
    
    if 'weight' in df.columns:
        weight_missing = missing_percent['weight']
        if weight_missing > 90:
            print(f"\nDropping 'weight' column ({weight_missing:.2f}% missing).")
            df.drop(columns=['weight'], inplace=True)
            
    deceased_ids = [11, 19, 20, 21]
    print(f"\nFiltering deceased patients (Discharge IDs: {deceased_ids})...")
    initial_count = len(df)
    df = df[~df['discharge_disposition_id'].isin(deceased_ids)]
    print(f"Removed {initial_count - len(df)} records. New count: {len(df)}")
    
    # 4. Deduplication
    print("\nChecking for duplicates...")
    dupes = df.duplicated().sum()
    if dupes > 0:
        print(f"Found {dupes} duplicates. Dropping...")
        df.drop_duplicates(inplace=True)
    else:
        print("No duplicates found.")
        
    # 5. Merge Mappings
    mappings = parse_ids_mapping(MAPPING_PATH)
    if mappings:
        for col, mapping_dict in mappings.items():
            desc_col = col.replace('_id', '_desc')
            df[desc_col] = df[col].map(mapping_dict).fillna("Not Mapped")
            
    # 6. Convert Data Types (IDs and Objects to Category)
    print("\nConverting data types to 'Category'...")
    
    id_cols = ['admission_type_id', 'discharge_disposition_id', 'admission_source_id']
    for col in id_cols:
        if col in df.columns:
            df[col] = df[col].astype('category')
            print(f"Converted {col} (int) -> Category")

    print("Converting object columns to categories...")
    for col in df.select_dtypes(include=['object']).columns:
        if col not in ['encounter_id', 'patient_nbr']:
            df[col] = df[col].astype('category')
            
    print(f"\nPhase 1 Complete. Final Shape: {df.shape}")
    
    return df

def get_icd9_description(code):
    """
    Scrapes ICD-9 description from a public repository.
    """
    url = f"http://icd9.chrisendres.com/index.php?action=search&srchtext={code}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            time.sleep(1)
            
            text_content = soup.get_text()
            if "No results found" in text_content:
                return "Description Not Found"
            
            for line in text_content.split('\n'):
                if code in line and len(line) > len(code) + 5:
                    return line.strip()
            
            return "Description Found but cleanup needed"
        else:
            return "Lookup Failed"
    except Exception as e:
        print(f"Error scraping {code}: {e}")
        return "Scraping Error"

def phase_2_enrichment(df):
    print("\n--- PHASE 2: DATA ENRICHMENT (WEB SCRAPING) ---")
    
    # 1. Identify Top 20 Diagnoses
    if 'diag_1' not in df.columns:
        print("Error: diag_1 column missing.")
        return df
        
    top_20_codes = df['diag_1'].value_counts().head(20).index.tolist()
    print(f"Top 20 ICD-9 Codes: {top_20_codes}")
    
    # 2. Scrape Descriptions
    code_map = {}
    print("Scraping descriptions (this may take 20+ seconds)...")
    
    for code in top_20_codes:
        if str(code) == 'nan' or str(code) == '?':
            continue
            
        desc = get_icd9_description(code)
        code_map[code] = desc
        print(f"Scraped {code}: {desc[:50]}...")
        
    # 3. Integration
    print("Mapping descriptions to dataframe...")
    df['Primary_Diagnosis_Desc'] = df['diag_1'].map(code_map).fillna("Other")
    
    # Convert new column to category for consistency
    df['Primary_Diagnosis_Desc'] = df['Primary_Diagnosis_Desc'].astype('category')
    
    return df

def phase_3_eda(df):
    print("\n--- PHASE 3: EXPLORATORY DATA ANALYSIS ---")
    
    # === 1. THE READMISSION LANDSCAPE ===
    print("\n1. Analyzing Readmission Distribution...")
    plt.figure(figsize=(8, 6))
    sns.countplot(process_readmitted_col(df))
    plt.title("Distribution of Readmission Status (Class Imbalance)")
    plt.savefig(os.path.join(PLOTS_DIR, "readmission_distribution.png"))
    plt.close()
    print("Saved readmission_distribution.png")
    
    # === 2. DEMOGRAPHIC PROFILING ===
    print("\n2. Demographic Profiling...")
    
    # 2.1 Age Distribution
    plt.figure(figsize=(10, 6))
    sns.countplot(x='age', data=df, order=df['age'].value_counts().index)
    plt.title("Age Distribution of Patients")
    plt.xticks(rotation=45)
    plt.savefig(os.path.join(PLOTS_DIR, "age_distribution.png"))
    plt.close()
    print("Saved age_distribution.png")
    
    demo_df = df[ (df['race'] != '?') & (df['gender'] != 'Unknown/Invalid')].copy()
    demo_df['is_readmitted'] = demo_df['readmitted'].apply(lambda x: 0 if x == 'NO' else 1)
    rate_df = demo_df.groupby(['race', 'gender'])['is_readmitted'].mean().reset_index()
    
    plt.figure(figsize=(12, 6))
    sns.barplot(data=rate_df, x='race', y='is_readmitted', hue='gender')
    plt.title("Readmission Rate by Race and Gender (Intersectional Disparity)")
    plt.ylabel("Readmission Rate (Percent)")
    plt.xticks(rotation=45)
    plt.savefig(os.path.join(PLOTS_DIR, "race_gender_readmission_rate.png"))
    plt.close()
    print("Saved race_gender_readmission_rate.png")
    
    plt.figure(figsize=(10, 6))
    sns.countplot(data=demo_df, x='race', hue='readmitted')
    plt.title("Readmission by Race")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "readmission_by_race.png"))
    plt.close()
    print("Saved readmission_by_race.png")
    
    # === 3. MEDICATION EFFICACY ANALYSIS ===
    print("\n3. Medication Efficacy Analysis...")
    
    # Define the 22 Oral Medications
    oral_meds = [
        'metformin', 'repaglinide', 'nateglinide', 'chlorpropamide', 
        'glimepiride', 'acetohexamide', 'glipizide', 'glyburide', 'tolbutamide', 
        'pioglitazone', 'rosiglitazone', 'acarbose', 'miglitol', 'troglitazone', 
        'tolazamide', 'examide', 'citoglipton', 'glyburide-metformin', 
        'glipizide-metformin', 'glimepiride-pioglitazone', 'metformin-rosiglitazone', 
        'metformin-pioglitazone'
    ]
    
    def determine_med_group(row):
        if row['insulin'] != 'No':
            return 'Insulin'
        for med in oral_meds:
            if med in row and row[med] != 'No':
                return 'Oral'
        return 'No Medication'

    print("Classifying Medication Cohorts...")
    df['Medication_Group'] = df.apply(determine_med_group, axis=1)
    
    # Calculate Binary Readmission for Rates
    df['is_readmitted'] = df['readmitted'].apply(lambda x: 0 if x == 'NO' else 1)

    # 3.1 Insulin vs Oral vs No Medication
    med_rate = df.groupby('Medication_Group')['is_readmitted'].mean().reset_index()
    
    plt.figure(figsize=(10, 6))
    sns.barplot(data=med_rate, x='Medication_Group', y='is_readmitted', order=['No Medication', 'Oral', 'Insulin'])
    plt.title("Readmission Rate by Medication Group (Severity Proxy)")
    plt.ylabel("Readmission Rate (Percent)")
    plt.savefig(os.path.join(PLOTS_DIR, "medication_efficacy_group.png"))
    plt.close()
    print("Saved medication_efficacy_group.png")
    
    # 3.2 Medication Change Analysis
    change_rate = df.groupby('change')['is_readmitted'].mean().reset_index()
    
    plt.figure(figsize=(8, 6))
    sns.barplot(data=change_rate, x='change', y='is_readmitted')
    plt.title("Readmission Rate by Medication Change Status")
    plt.ylabel("Readmission Rate (Percent)")
    plt.savefig(os.path.join(PLOTS_DIR, "medication_change_impact.png"))
    plt.close()
    print("Saved medication_change_impact.png")

    # === 4. OPERATIONAL METRICS ===
    print("\n4. Operational Metrics Analysis...")
    
    # 4.1 Time in Hospital vs Lab Procedures (Linear Correlation)
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=df, x='time_in_hospital', y='num_lab_procedures', alpha=0.1)
    plt.title("Time in Hospital vs Lab Procedures")
    plt.savefig(os.path.join(PLOTS_DIR, "hospital_vs_lab.png"))
    plt.close()
    print("Saved hospital_vs_lab.png")
    
    # 4.2 Correlation Heatmap
    num_cols = ['time_in_hospital', 'num_lab_procedures', 'num_procedures', 'num_medications', 'number_diagnoses']
    corr_matrix = df[num_cols].corr()
    plt.figure(figsize=(12, 10), dpi=300)
    sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', fmt=".2f", annot_kws={"size": 12})
    plt.title("Correlation Heatmap of Operational Metrics", fontsize=14, pad=20)
    plt.xticks(fontsize=11)
    plt.yticks(fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "correlation_heatmap.png"), dpi=300, bbox_inches='tight')
    plt.close()
    print("Saved correlation_heatmap.png")
    
    # 4.3 Box Plot: Time in Hospital by Readmission
    plt.figure(figsize=(8, 6))
    sns.boxplot(data=df, x=process_readmitted_col(df), y='time_in_hospital')
    plt.title("Time in Hospital by Readmission Status")
    plt.savefig(os.path.join(PLOTS_DIR, "readmission_los_boxplot.png"))
    plt.close()
    print("Saved readmission_los_boxplot.png")
    
    # 4.4 Discharge Disposition Analysis (SNF vs Home)
    if 'discharge_disposition_desc' in df.columns:
        subset = df[df['discharge_disposition_desc'].str.contains('Home|Skilled', case=False, na=False)]
        
        plt.figure(figsize=(12, 6))
        sns.countplot(data=subset, y='discharge_disposition_desc', hue='readmitted')
        plt.title("Readmission by Discharge Disposition (Home vs SNF)")
        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, "discharge_disposition_analysis.png"))
        plt.close()
        print("Saved discharge_disposition_analysis.png")

    return df


def process_readmitted_col(df):
    if 'readmitted' in df.columns:
        return df['readmitted']
    return pd.Series()

def calculate_vci(row):
    # L - Length of Stay
    l_score = 0
    los = row['time_in_hospital']
    if los < 1: l_score = 0
    elif 1 <= los <= 4: l_score = 1
    elif 5 <= los <= 13: l_score = 4
    elif los >= 14: l_score = 7
    
    a_score = 0
    if row['admission_type_id'] in [1, 7]:
        a_score = 3
        
    # C - Comorbidity
    c_score = 0
    num_diag = row['number_diagnoses']
    if num_diag < 4: c_score = 0
    elif 4 <= num_diag <= 7: c_score = 3
    elif num_diag >= 8: c_score = 5
    
    # E - Emergency Visits
    e_score = 0
    num_em = row['number_emergency']
    if num_em == 0: e_score = 0
    elif 1 <= num_em <= 4: e_score = 3
    elif num_em > 4: e_score = 5
    
    return l_score + a_score + c_score + e_score

def phase_4_feature_engineering(df):
    print("\n--- PHASE 4: FEATURE ENGINEERING (VCI) ---")
    
    # 1. Calculate VCI
    print("Calculating Vitality Complexity Index (VCI)...")
    df['VCI_Score'] = df.apply(calculate_vci, axis=1)
    
    # 2. Stratification
    def stratify(score):
        if score < 7: return 'Low Risk'
        elif 7 <= score <= 10: return 'Medium Risk'
        else: return 'High Risk'
        
    df['Risk_Category'] = df['VCI_Score'].apply(stratify)
    
    print(df['Risk_Category'].value_counts())
    
    plt.figure(figsize=(10, 6))
    sns.countplot(data=df, x='Risk_Category', hue='readmitted', order=['Low Risk', 'Medium Risk', 'High Risk'])
    plt.title("Readmission Distribution by VCI Risk Category")
    plt.savefig(os.path.join(PLOTS_DIR, "vci_validation.png"))
    plt.close()
    print("Saved vci_validation.png")
    
    return df

def generate_report_summary(df):
    print("\n--- GENERATING SUMMARY ---")
    print(f"Total Patients Analyzed: {len(df)}")
    if 'readmitted' in df.columns:
        print("Readmission Rates:")
        print(df['readmitted'].value_counts(normalize=True))
    
    print("Top 5 Diagnoses (Enriched):")
    if 'Primary_Diagnosis_Desc' in df.columns:
        print(df['Primary_Diagnosis_Desc'].value_counts().head())

if __name__ == "__main__":
    df = phase_1_sanitation()
    df = phase_2_enrichment(df)
    df = phase_3_eda(df)
    df = phase_4_feature_engineering(df)
    generate_report_summary(df)
