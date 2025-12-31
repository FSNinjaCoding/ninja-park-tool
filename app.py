import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from datetime import datetime

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

st.set_page_config(page_title="Ninja Park Processor", layout="wide")

# --- HELPER FUNCTIONS ---

def clean_name(name):
    """Standardizes names (Title Case, no extra spaces)."""
    if not isinstance(name, str): return ""
    return re.sub(r'\s+', ' ', name).strip().title()

def parse_class_info(class_name):
    """
    Extracts Day and Time from Class Name.
    Example: "Flip Side Ninjas... | Mon: 3:40 - 4:40" -> ("Mon", 1540)
    """
    if not isinstance(class_name, str) or class_name == "Not Found":
        return "Lost", 9999, ""
    
    # Extract Day
    day_match = re.search(r'\b(Mon|Tue|Wed|Thu|Fri)\b', class_name, re.IGNORECASE)
    day = day_match.group(1).title() if day_match else "Lost"
    
    # Extract Start Time
    time_match = re.search(r'(\d{1,2}):(\d{2})', class_name)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if hour < 8: hour += 12 # Assume PM unless morning
        sort_time = hour * 100 + minute
        time_str = f"{time_match.group(1)}:{time_match.group(2)}"
    else:
        sort_time = 9999
        time_str = ""
        
    return day, sort_time, time_str

def parse_skill_number(skill_str):
    """Converts 's3' to integer 3 for sorting."""
    match = re.search(r'(\d+)', str(skill_str))
    return int(match.group(1)) if match else 0

def parse_group_number(group_str):
    """Converts 'Group 1' to integer 1 for sorting."""
    match = re.search(r'(\d+)', str(group_str))
    return int(match.group(1)) if match else 99

def parse_attendance(att_str):
    try: return int(att_str)
    except: return -1

def parse_age(age_str):
    match = re.search(r'(\d+)', str(age_str))
    return int(match.group(1)) if match else 99

# --- PARSING LOGIC ---
def parse_roll_sheet(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    current_class_name = "Unknown Class"
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        first_row_cols = [c.get_text(strip=True) for c in rows[0].find_all(['td', 'th'])]
        
        if len(first_row_cols) > 0 and ("|" in first_row_cols[0] or "Ninja" in first_row_cols[0]):
            if "Student" not in first_row_cols[0]: 
                current_class_name = first_row_cols[0]
                continue

        is_student_table = False
        name_idx, detail_idx = 1, 3
        for idx, col_text in enumerate(first_row_cols):
            if "Student" in col_text:
                is_student_table = True
                name_idx = idx
                for sub_idx, sub_text in enumerate(first_row_cols):
                    if "Details" in sub_text: detail_idx = sub_idx
                break
        
        if is_student_table:
            for row in rows[1:]:
                cols = row.find_all(['td', 'th'])
                def get_val(i): return cols[i].get_text(strip=True) if i < len(cols) else ""
                
                raw_name = get_val(name_idx)
                details_text = get_val(detail_idx).lower()
                skill_level = "s0"
                skill_match = re.search(r's([0-9]|10)\b', details_text)
                if skill_match: skill_level = skill_match.group(0)
                
                if raw_name:
                    data.append({
                        "Student Name": clean_name(raw_name),
                        "Skill Level": skill_level,
                        "Class Name": current_class_name
                    })
    
    df = pd.DataFrame(data)
    if not df.empty: df = df.drop_duplicates(subset=["Student Name"], keep='first')
    return df

def parse_student_list(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['td', 'th'])]
        
        name_idx, att_idx, age_idx, key_idx, comm_idx = 1, 2, 3, 4, 5
        for i, h in enumerate(headers):
            if "student name" in h: name_idx = i
            elif "age" in h: age_idx = i
            elif "keyword" in h: key_idx = i
            elif "attendance" in h: att_idx = i
            elif "comment" in h: comm_idx = i

        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            def get_val(i): return cols[i].get_text(strip=True) if i < len(cols) else ""
            
            raw_name = get_val(name_idx)
            age = get_val(age_idx)
            attendance = get_val(att_idx)
            comment = get_val(comm_idx)
            keywords_raw = get_val(key_idx).lower()
            
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
    if not df.empty: df = df.drop_duplicates(subset=["Student Name"])
    return df

# --- HIGHLIGHTING LOGIC ---

def get_row_color(row, purple_groups):
    """
    Returns highlight color based on Priority: Red > Orange > Yellow > Purple.
    """
    skill_num = parse_skill_number(row["Skill Level"])
    group_num = parse_group_number(row["Student Keyword"])
    class_name_lower = row["Class Name"].lower()

    # PRIORITY 1: RED
    # If class does NOT contain "advanced" AND skill is s3 or higher
    if "advanced" not in class_name_lower and skill_num >= 3:
        return {"red": 1.0, "green": 0.8, "blue": 0.8} # Light Red

    # PRIORITY 2: ORANGE
    # If Group 1 has s2 or higher
    if group_num == 1 and skill_num >= 2:
        return {"red": 1.0, "green": 0.9, "blue": 0.8} # Light Orange

    # PRIORITY 3: YELLOW
    # If group is blank
    if row["Student Keyword"] == "":
        return {"red": 1.0, "green": 1.0, "blue": 0.8} # Light Yellow

    # PRIORITY 4: PURPLE
    # If group has >2 skill levels AND class is NOT "Advanced", highlight max skill
    # We check if this specific row is the "Max Skill" for its group
    group_key = (row['Class Name'], row['Student Keyword'])
    if group_key in purple_groups:
        max_skill_in_group = purple_groups[group_key]
        if skill_num == max_skill_in_group:
            return {"red": 0.85, "green": 0.8, "blue": 1.0} # Light Purple

    return None # No highlight

def update_google_sheet_multitab(full_df):
    if "gcp_service_account" not in st.secrets:
        st.error("Secrets not found!")
        return None

    creds_dict = st.secrets["gcp_service_account"]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        ss = client.open(GOOGLE_SHEET_NAME)
    except Exception as e:
        st.error(f"Could not open sheet: {e}")
        return None

    # --- PRE-CALCULATE PURPLE GROUPS ---
    # Rule: Group must have >2 unique skill levels AND Class must NOT be "Advanced"
    purple_groups = {} 
    
    valid_data = full_df[full_df['Sort Day'] != 'Lost'].copy()
    valid_data['skill_int'] = valid_data['Skill Level'].apply(parse_skill_number)
    
    for (cls, grp), group_df in valid_data.groupby(['Class Name', 'Student Keyword']):
        if not grp: continue # Skip blank groups
        
        # SKIP if class contains "Advanced"
        if "advanced" in cls.lower(): 
            continue 

        unique_skills = group_df['skill_int'].unique()
        if len(unique_skills) > 2:
            purple_groups[(cls, grp)] = group_df['skill_int'].max()

    # --- PROCESS TABS ---
    days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Lost"]
    
    # Clean up old sheets
    try:
        worksheets = ss.worksheets()
        if len(worksheets) > 1:
            for ws in worksheets[1:]: ss.del_worksheet(ws)
    except: pass

    first_tab = True
    for day in days_order:
        if day == "Lost":
            day_df = full_df[full_df["Sort Day"] == "Lost"].copy()
        else:
            day_df = full_df[full_df["Sort Day"] == day].copy()
            
        if day_df.empty: continue

        # SORTING
        day_df['sort_group'] = day_df['Student Keyword'].apply(parse_group_number)
        day_df['sort_skill'] = day_df['Skill Level'].apply(parse_skill_number)
        day_df['sort_att'] = day_df['Attendance'].apply(parse_attendance)
        day_df['sort_age'] = day_df['Age'].apply(parse_age)
        
        day_df = day_df.sort_values(
            by=['Sort Time', 'sort_group', 'sort_skill', 'sort_att', 'sort_age'],
            ascending=[True, True, True, True, True]
        )
        
        # PREPARE EXPORT
        export_cols = ["Student Name", "Age", "Attendance", "Student Keyword", "Skill Level", "Class Name", "Roll Sheet Comment"]
        for c in export_cols:
            if c not in day_df.columns: day_df[c] = ""
        export_df = day_df[export_cols]

        try:
            ws = ss.worksheet(day)
            ws.clear()
        except:
            ws = ss.add_worksheet(title=day, rows=100, cols=20)
        
        ws.update([export_df.columns.values.tolist()] + export_df.values.tolist())
        
        # BATCH FORMATTING
        requests = []
        rows = export_df.to_dict('records')
        
        for i, row in enumerate(rows):
            color = get_row_color(row, purple_groups)
            if color:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": i + 1,
                            "endRowIndex": i + 2,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(export_cols)
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": color
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor"
                    }
                })
        
        if requests:
            ss.batch_update({"requests": requests})
        
        if first_tab and len(ss.worksheets()) > 1:
            try:
                sheet1 = ss.worksheet("Sheet1")
                ss.del_worksheet(sheet1)
            except: pass
        first_tab = False

    return f"https://docs.google.com/spreadsheets/d/{ss.id}"


# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor 2.0")
st.write("Multi-Tab Edition with Priority Highlighting")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

if roll_file and list_file:
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Parsing, Sorting & Coloring...'):
        try:
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())

            if df_roll.empty: st.warning("⚠️ No data in Roll Sheet.")
            if df_list.empty: st.warning("⚠️ No data in Student List.")

            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            merged_df[['Sort Day', 'Sort Time', 'Time Str']] = merged_df['Class Name'].apply(
                lambda x: pd.Series(parse_class_info(x))
            )

            merged_df.loc[merged_df['Sort Day'] == "Lost", 'Sort Day'] = "Lost"

            st.success(f"Processed {len(merged_df)} students.")
            
            if st.button("Update Master Google Sheet", use_container_width=True):
                link = update_google_sheet_multitab(merged_df)
                if link:
                    st.success("Google Sheet Updated Successfully!")
                    st.markdown(f'<a href="{link}" target="_blank" style="background-color:#0083B8;color:white;padding:10px;text-decoration:none;border-radius:5px;display:inline-block;">OPEN GOOGLE SHEET ⬈</a>', unsafe_allow_html=True)
                        
        except Exception as e:
            st.error(f"Detailed Error: {e}")
