import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- CONFIGURATION ---
# The exact name of the Google Sheet you created in your Drive
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

st.set_page_config(page_title="Ninja Park Processor", layout="wide")

def clean_name(name):
    """Standardizes names (Title Case, no extra spaces)."""
    if not isinstance(name, str): return ""
    return re.sub(r'\s+', ' ', name).strip().title()

def parse_roll_sheet(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    # The Roll Sheet is made of hundreds of small tables.
    tables = soup.find_all('table')
    
    current_class_name = "Unknown Class"
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        
        # Check first row to identify table type
        first_row_cols = [c.get_text(strip=True) for c in rows[0].find_all(['td', 'th'])]
        
        # CASE 1: Class Header (e.g., "Advanced Ninja... | Thu: 6:00")
        if len(first_row_cols) > 0 and ("|" in first_row_cols[0] or "Ninja" in first_row_cols[0]):
            if "Student" not in first_row_cols[0]: 
                current_class_name = first_row_cols[0]
                continue

        # CASE 2: Student Data
        is_student_table = False
        name_idx = 1 # Default
        detail_idx = 3 # Default
        
        for idx, col_text in enumerate(first_row_cols):
            if "Student" in col_text:
                is_student_table = True
                name_idx = idx
                for sub_idx, sub_text in enumerate(first_row_cols):
                    if "Details" in sub_text:
                        detail_idx = sub_idx
                break
        
        if is_student_table:
            for row in rows[1:]:
                cols = row.find_all(['td', 'th'])
                # Safe Extraction Helper
                def get_val(i): return cols[i].get_text(strip=True) if i < len(cols) else ""
                
                raw_name = get_val(name_idx)
                details_text = get_val(detail_idx).lower()
                
                # Extract Skill Level (s1-s10)
                skill_level = "s0"
                skill_match = re.search(r's([0-9]|10)\b', details_text)
                if skill_match:
                    skill_level = skill_match.group(0)
                
                if raw_name:
                    data.append({
                        "Student Name": clean_name(raw_name),
                        "Skill Level": skill_level,
                        "Class Name": current_class_name
                    })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"], keep='first')
    return df

def parse_student_list(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        
        # Detect Headers
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['td', 'th'])]
        
        # Defaults based on your file
        name_idx = 1
        att_idx = 2
        age_idx = 3
        key_idx = 4
        comm_idx = 5
        
        # Dynamic Header Search
        for i, h in enumerate(headers):
            if "student name" in h: name_idx = i
            elif "age" in h: age_idx = i
            elif "keyword" in h: key_idx = i
            elif "attendance" in h: att_idx = i
            elif "comment" in h: comm_idx = i

        # Parse Rows
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            
            # SAFE EXTRACTION: This prevents skipping rows if the last column is empty
            def get_val(i): return cols[i].get_text(strip=True) if i < len(cols) else ""

            raw_name = get_val(name_idx)
            age = get_val(age_idx)
            attendance = get_val(att_idx)
            comment = get_val(comm_idx)
            keywords_raw = get_val(key_idx).lower()
            
            # Filter Keywords
            group_match = re.search(r'(group\s*[1-3])', keywords_raw)
            clean_keyword = group_match.group(0).capitalize() if group_match else ""

            if raw_name:
                data.append({
                    "Student Name": clean_name(raw_name),
                    "Age": age,
                    "Attendance": attendance,
                    "Roll Sheet Comment": comment,
                    "Student Keyword": clean_keyword
                })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"])
    return df

def update_google_sheet(df):
    if "gcp_service_account" not in st.secrets:
        st.error("Secrets not found!")
        return None

    creds_dict = st.secrets["gcp_service_account"]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        # Open existing sheet
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}"
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ Could not find Google Sheet '{GOOGLE_SHEET_NAME}'.")
        st.info(f"Please create it and share with: {creds_dict['client_email']}")
        return None
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor")
st.write("Upload your iClassPro HTML files below.")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

if roll_file and list_file:
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Processing...'):
        try:
            # Parse
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())

            if df_roll.empty: st.warning("⚠️ No data in Roll Sheet.")
            if df_list.empty: st.warning("⚠️ No data in Student List.")

            # Merge
            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            
            # Fill Blanks
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            # Final Column Selection
            final_cols = ["Student Name", "Age", "Attendance", "Roll Sheet Comment", "Student Keyword", "Skill Level", "Class Name"]
            
            # Ensure cols exist
            for c in final_cols:
                if c not in merged_df.columns: merged_df[c] = ""
            
            final_df = merged_df[final_cols]
            
            st.success(f"Matched {len(final_df)} students!")
            st.dataframe(final_df, use_container_width=True)
            
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    label="Download CSV",
                    data=final_df.to_csv(index=False).encode('utf-8'),
                    file_name='ninja_output.csv',
                    mime='text/csv',
                    use_container_width=True
                )
            with c2:
                if st.button("Update Master Google Sheet", use_container_width=True):
                    link = update_google_sheet(final_df)
                    if link:
                        st.success("Google Sheet Updated!")
                        st.markdown(f'<a href="{link}" target="_blank" style="background-color:#0083B8;color:white;padding:10px;text-decoration:none;border-radius:5px;display:inline-block;">OPEN GOOGLE SHEET ⬈</a>', unsafe_allow_html=True)
                        
        except Exception as e:
            st.error(f"Error: {e}")
