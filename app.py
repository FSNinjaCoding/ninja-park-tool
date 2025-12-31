import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

st.set_page_config(page_title="Ninja Park Processor 3.0", layout="wide")

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
    match = re.search(r'(\d+)', str(skill_str))
    return int(match.group(1)) if match else 0

def parse_group_number(group_str):
    match = re.search(r'(\d+)', str(group_str))
    return int(match.group(1)) if match else 99

def parse_attendance(att_str):
    try: return int(att_str)
    except: return -1

def parse_age(age_str):
    match = re.search(r'(\d+)', str(age_str))
    return int(match.group(1)) if match else 99

# --- PARSING LOGIC (Standard) ---
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

# --- COLOR LOGIC ---

def get_row_color(row, purple_groups, is_last_in_group):
    """
    Returns highlight color.
    Priority: Red > Green > Orange > Yellow > Purple
    """
    # 0. IGNORE RULE: Check comment first
    if "ignore" in str(row["Roll Sheet Comment"]).lower():
        return None

    skill_num = parse_skill_number(row["Skill Level"])
    group_num = parse_group_number(row["Student Keyword"])
    class_name_lower = row["Class Name"].lower()

    # 1. RED (Class != Advanced AND Skill >= 3)
    if "advanced" not in class_name_lower and skill_num >= 3:
        return {"red": 1.0, "green": 0.8, "blue": 0.8} # Light Red

    # 2. GREEN (Last student in Group)
    if is_last_in_group:
        return {"red": 0.8, "green": 1.0, "blue": 0.8} # Light Green

    # 3. ORANGE (Group 1 AND Skill >= 2)
    if group_num == 1 and skill_num >= 2:
        return {"red": 1.0, "green": 0.9, "blue": 0.8} # Light Orange

    # 4. YELLOW (Group Blank)
    if row["Student Keyword"] == "":
        return {"red": 1.0, "green": 1.0, "blue": 0.8} # Light Yellow

    # 5. PURPLE (Max Skill in Mixed Group)
    group_key = (row['Class Name'], row['Student Keyword'])
    if group_key in purple_groups:
        max_skill = purple_groups[group_key]
        if skill_num == max_skill:
            return {"red": 0.85, "green": 0.8, "blue": 1.0} # Light Purple

    return None

def update_google_sheet_advanced(full_df):
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

    # --- 1. PRE-CALCULATE PURPLE GROUPS ---
    purple_groups = {}
    valid_data = full_df[full_df['Sort Day'] != 'Lost'].copy()
    valid_data['skill_int'] = valid_data['Skill Level'].apply(parse_skill_number)
    
    for (cls, grp), group_df in valid_data.groupby(['Class Name', 'Student Keyword']):
        if not grp or "advanced" in cls.lower(): continue
        if len(group_df['skill_int'].unique()) > 2:
            purple_groups[(cls, grp)] = group_df['skill_int'].max()

    # --- 2. PROCESS DAYS ---
    days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Lost"]
    
    # Cleanup old sheets
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

        # Get Worksheet
        try:
            ws = ss.worksheet(day)
            ws.clear()
        except:
            ws = ss.add_worksheet(title=day, rows=100, cols=100) # Wide sheet for side-by-side

        # --- 3. PROCESS EACH TIME SLOT SIDE-BY-SIDE ---
        # Get unique times for this day, sorted
        unique_times = sorted(day_df['Sort Time'].unique())
        
        current_col_idx = 1 # Start at Column A
        requests = [] # For batch formatting
        
        # Column headers we want to display
        export_cols = ["Student Name", "Age", "Attendance", "Student Keyword", "Skill Level", "Class Name", "Roll Sheet Comment"]
        
        for time_slot in unique_times:
            # Filter Data for this specific time
            time_df = day_df[day_df['Sort Time'] == time_slot].copy()
            
            # SORTING LOGIC
            time_df['sort_group'] = time_df['Student Keyword'].apply(parse_group_number)
            time_df['sort_skill'] = time_df['Skill Level'].apply(parse_skill_number)
            time_df['sort_att'] = time_df['Attendance'].apply(parse_attendance)
            time_df['sort_age'] = time_df['Age'].apply(parse_age)
            
            # FIXED SORTING CALL
            time_df = time_df.sort_values(
                by=['sort_group', 'sort_skill', 'sort_att', 'sort_age'],
                ascending=[True, True, True, True]
            )
            
            # Determine "Last in Group" for Green Highlight
            time_df['is_last_in_group'] = time_df['Student Keyword'] != time_df['Student Keyword'].shift(-1)
            time_df.loc[time_df['Student Keyword'] == "", 'is_last_in_group'] = False
            
            # Prepare Data Block
            for c in export_cols:
                if c not in time_df.columns: time_df[c] = ""
            
            final_data_block = time_df[export_cols]
            
            # Write Header + Data to Grid
            values = [export_cols] + final_data_block.values.tolist()
            
            # Update cells (gspread uses row, col indices)
            ws.update(
                range_name=None, 
                values=values, 
                start_row=1, 
                start_col=current_col_idx
            )
            
            # Formatting Loop for this block
            rows = final_data_block.to_dict('records')
            is_last_list = time_df['is_last_in_group'].tolist()
            
            for i, row in enumerate(rows):
                # +1 for header, +1 because sheets is 1-indexed -> Start at row 2
                sheet_row = i + 1 
                
                color = get_row_color(row, purple_groups, is_last_list[i])
                
                if color:
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": sheet_row,      # Row index (0-based)
                                "endRowIndex": sheet_row + 1,
                                "startColumnIndex": current_col_idx - 1, # Col index (0-based)
                                "endColumnIndex": current_col_idx - 1 + len(export_cols)
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color
                                }
                            },
                            "fields": "userEnteredFormat.backgroundColor"
                        }
                    })
            
            # Move Column Pointer: 7 columns of data + 1 empty column gap
            current_col_idx += (len(export_cols) + 1)

        # Batch Execute Formatting
        if requests:
            ss.batch_update({"requests": requests})
            
        # Cleanup "Sheet1"
        if first_tab and len(ss.worksheets()) > 1:
            try:
                sheet1 = ss.worksheet("Sheet1")
                ss.del_worksheet(sheet1)
            except: pass
        first_tab = False

    return f"https://docs.google.com/spreadsheets/d/{ss.id}"


# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor 3.0")
st.write("Dashboard Layout with Advanced Logic")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

if roll_file and list_file:
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Building Dashboard... (This may take 10-20 seconds)...'):
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
                link = update_google_sheet_advanced(merged_df)
                if link:
                    st.success("Google Sheet Updated Successfully!")
                    st.markdown(f'<a href="{link}" target="_blank" style="background-color:#0083B8;color:white;padding:10px;text-decoration:none;border-radius:5px;display:inline-block;">OPEN GOOGLE SHEET ⬈</a>', unsafe_allow_html=True)
                        
        except Exception as e:
            st.error(f"Detailed Error: {e}")
