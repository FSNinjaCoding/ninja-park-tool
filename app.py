import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

st.set_page_config(page_title="Ninja Park Processor 3.5", layout="wide")

# --- HELPER FUNCTIONS ---

def clean_name(name):
    """Standardizes names (Title Case, no extra spaces)."""
    if not isinstance(name, str): return ""
    clean = re.sub(r'\s+', ' ', name).replace(u'\xa0', ' ').strip()
    return clean.title()

def abbreviate_class_name(name):
    """Shortens class names to save space."""
    if not isinstance(name, str): return name
    # Remove date ranges
    name = re.sub(r'\d{1,2}/\d{1,2}/\d{4}.*', '', name).strip()
    
    name = name.replace("Homeschool", "HS")
    name = name.replace("Flip Side Ninjas", "FS Ninjas")
    name = name.replace("(Ages ", "(")
    return name

def parse_class_info(class_name):
    if not isinstance(class_name, str) or class_name == "Not Found":
        return "Lost", 9999, ""
    
    day_match = re.search(r'\b(Mon|Tue|Wed|Thu|Fri)\b', class_name, re.IGNORECASE)
    day = day_match.group(1).title() if day_match else "Lost"
    
    time_match = re.search(r'(\d{1,2}):(\d{2})', class_name)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if hour < 8: hour += 12 
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

# --- PARSING LOGIC ---
def parse_roll_sheet(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    headers = soup.find_all('div', class_='full-width-header')
    
    if not headers:
        st.warning("⚠️ Formatting warning: Could not find standard class headers. Check HTML file.")

    for header in headers:
        name_span = header.find('span')
        if name_span:
            class_name_raw = name_span.get_text(strip=True)
        else:
            class_name_raw = header.get_text(separator=" ", strip=True)
            
        current_class_name = class_name_raw if class_name_raw else "Unknown Class"
        
        table = header.find_next('table', class_='table-roll-sheet')
        next_header = header.find_next('div', class_='full-width-header')
        
        if table and next_header:
            h_line = next_header.sourceline
            t_line = table.sourceline
            if h_line is not None and t_line is not None:
                if h_line < t_line:
                    continue 

        if not table: continue

        rows = table.find_all('tr')
        if not rows: continue
        
        first_row_cols = [c.get_text(strip=True) for c in rows[0].find_all(['td', 'th'])]
        name_idx, detail_idx = 1, 3 
        
        for idx, col_text in enumerate(first_row_cols):
            if "Student" in col_text: name_idx = idx
            if "Details" in col_text: detail_idx = idx
            
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            def get_val(i): return cols[i].get_text(strip=True) if i < len(cols) else ""
            
            raw_name = get_val(name_idx)
            details_text = get_val(detail_idx).lower()
            
            skill_level = "s0"
            skill_match = re.search(r's([0-9]|10)\b', details_text)
            if skill_match: skill_level = skill_match.group(0)
            
            if raw_name and len(raw_name) > 1 and "Student" not in raw_name:
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

            if raw_name and len(raw_name) > 1:
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

# --- FORMATTING LOGIC ---

def get_base_row_format(row, day):
    """
    Determines the Base Highlight (Red, Orange, Yellow, Purple) 
    based on the Day and Rules.
    Returns a Dict representing the Format or None.
    """
    if not row.get("Student Name") or str(row["Student Name"]).strip() == "":
        return None

    if "ignore" in str(row["RS Comment"]).lower():
        return None

    skill_num = parse_skill_number(row["Level"])
    group_num = parse_group_number(row["Keyword"])
    
    # --- COLORS ---
    COLOR_RED = {"red": 1.0, "green": 0.8, "blue": 0.8}
    COLOR_ORANGE = {"red": 1.0, "green": 0.9, "blue": 0.8}
    COLOR_YELLOW = {"red": 1.0, "green": 1.0, "blue": 0.8}
    
    # 1. ORANGE RULE (Priority: Blank Group)
    if row["Keyword"] == "":
        return {"backgroundColor": COLOR_ORANGE}

    # 2. RED RULE (Mon/Tue/Fri AND Skill >= 3) -> Bold Text & Red Background
    if day in ["Mon", "Tue", "Fri"] and skill_num >= 3:
        return {
            "backgroundColor": COLOR_RED,
            "textFormat": {"bold": True}
        }

    # 3. YELLOW RULE (Day Specific)
    is_yellow = False
    
    if day in ["Mon", "Tue", "Fri"]:
        # G1 >= s2 OR G2 == s0 OR G3 <= s1
        if group_num == 1 and skill_num >= 2: is_yellow = True
        elif group_num == 2 and skill_num == 0: is_yellow = True
        elif group_num == 3 and skill_num <= 1: is_yellow = True
        
    elif day in ["Wed", "Thu"]:
        # G1 >= s5 OR G2 == s3/s7+ OR G3 <= s5
        if group_num == 1 and skill_num >= 5: is_yellow = True
        elif group_num == 2 and (skill_num == 3 or skill_num >= 7): is_yellow = True
        elif group_num == 3 and skill_num <= 5: is_yellow = True

    if is_yellow:
        return {"backgroundColor": COLOR_YELLOW}

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

    # --- 1. RENAME COLUMNS ---
    full_df = full_df.rename(columns={
        "Attendance": "Attend#",
        "Student Keyword": "Keyword",
        "Skill Level": "Level",
        "Roll Sheet Comment": "RS Comment"
    })

    # --- 2. PROCESS DAYS ---
    days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Lost"]
    
    try:
        sheet1 = ss.worksheet("Sheet1")
        ss.del_worksheet(sheet1)
    except: pass

    for day in days_order:
        if day == "Lost":
            day_df = full_df[full_df["Sort Day"] == "Lost"].copy()
        else:
            day_df = full_df[full_df["Sort Day"] == day].copy()
            
        if day_df.empty: continue

        # Nuclear Recreate
        try:
            old_ws = ss.worksheet(day)
            ss.del_worksheet(old_ws)
        except: pass 

        # --- CONSTRUCT GRID ---
        unique_times = sorted(day_df['Sort Time'].unique())
        slot_data_map = {}
        max_rows = 0
        export_cols = ["Student Name", "Age", "Attend#", "Keyword", "Level", "Class Name", "RS Comment"]
        
        for i, time_slot in enumerate(unique_times):
            time_df = day_df[day_df['Sort Time'] == time_slot].copy()
            
            # Sort
            time_df['sort_group'] = time_df['Keyword'].apply(parse_group_number)
            time_df['sort_skill'] = time_df['Level'].apply(parse_skill_number)
            time_df['sort_att'] = time_df['Attend#'].apply(parse_attendance)
            time_df['sort_age'] = time_df['Age'].apply(parse_age)
            
            time_df = time_df.sort_values(
                by=['sort_group', 'sort_skill', 'sort_att', 'sort_age'],
                ascending=[True, True, True, True]
            )
            
            for c in export_cols:
                if c not in time_df.columns: time_df[c] = ""
            
            # Insert Blank Rows & Prep for Formatting
            records = time_df.to_dict('records')
            final_records = []
            
            if records:
                prev_group = records[0]['sort_group']
                # Add index tracker for original group logic
                records[0]['_original_group_id'] = prev_group 
                final_records.append(records[0])
                
                for rec in records[1:]:
                    curr_group = rec['sort_group']
                    if curr_group != prev_group:
                        blank_row = {col: "" for col in export_cols}
                        blank_row['_is_blank_separator'] = True # Marker
                        final_records.append(blank_row)
                    
                    rec['_original_group_id'] = curr_group
                    final_records.append(rec)
                    prev_group = curr_group
            
            final_block = pd.DataFrame(final_records)
            if final_block.empty:
                final_block = pd.DataFrame(columns=export_cols)
            
            slot_data_map[i] = final_block
            if len(final_block) > max_rows: max_rows = len(final_block)

        # Build Grid Values
        headers = []
        for _ in unique_times:
            headers.extend(export_cols)
            headers.append("") 
        
        final_values = [headers]
        
        for r in range(max_rows):
            row_data = []
            for i in range(len(unique_times)):
                df = slot_data_map[i]
                if r < len(df):
                    row_list = []
                    for col in export_cols:
                        val = df.iloc[r].get(col, "")
                        row_list.append(val)
                    row_data.extend(row_list)
                else:
                    row_data.extend([""] * len(export_cols))
                row_data.append("")
            final_values.append(row_data)

        # Create Sheet
        total_cols = max(len(unique_times) * 8, 26) 
        total_rows = len(final_values) + 20 
        ws = ss.add_worksheet(title=day, rows=total_rows, cols=total_cols)
        ws.update(range_name="A1", values=final_values)
        
        # --- BATCH FORMATTING (Floating Green Logic) ---
        requests = []
        COLOR_GREEN = {"red": 0.8, "green": 1.0, "blue": 0.8}
        
        current_col_start = 0
        for i in range(len(unique_times)):
            df = slot_data_map[i]
            records = df.to_dict('records')
            
            # 1. Calculate Base Formats for ALL rows in this block
            row_formats = [None] * len(records)
            
            for idx, row in enumerate(records):
                if row.get('_is_blank_separator'):
                    continue
                row_formats[idx] = get_base_row_format(row, day)

            # 2. Apply Floating Green Logic per Group
            # We need to find the chunks of indices belonging to each group
            group_indices = {} # group_id -> list of indices
            
            for idx, row in enumerate(records):
                if row.get('_is_blank_separator') or not row.get('_original_group_id'):
                    continue
                g_id = row['_original_group_id']
                if g_id not in group_indices: group_indices[g_id] = []
                group_indices[g_id].append(idx)
            
            # Iterate each group backwards
            for g_id, indices in group_indices.items():
                indices.sort() # Ensure order
                found_green_candidate = False
                
                # Check from bottom up
                for idx in reversed(indices):
                    if row_formats[idx] is None:
                        # Found a slot with no highlight!
                        # Apply Green here
                        row_formats[idx] = {"backgroundColor": COLOR_GREEN}
                        found_green_candidate = True
                        break
                    else:
                        # This slot is already colored (Red/Orange/Yellow)
                        # Continue moving up...
                        pass
            
            # 3. Generate Requests
            for row_idx, fmt in enumerate(row_formats):
                if fmt:
                    sheet_row_index = row_idx + 1
                    
                    # Construct CellFormat
                    user_fmt = {}
                    if "backgroundColor" in fmt:
                        user_fmt["backgroundColor"] = fmt["backgroundColor"]
                    if "textFormat" in fmt:
                        user_fmt["textFormat"] = fmt["textFormat"]
                    
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": sheet_row_index,
                                "endRowIndex": sheet_row_index + 1,
                                "startColumnIndex": current_col_start,
                                "endColumnIndex": current_col_start + len(export_cols)
                            },
                            "cell": {"userEnteredFormat": user_fmt},
                            "fields": "userEnteredFormat(backgroundColor,textFormat)"
                        }
                    })
            
            current_col_start += (len(export_cols) + 1)

        # 4. Auto-Fit
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": total_cols
                }
            }
        })

        if requests:
            ss.batch_update({"requests": requests})

    return f"https://docs.google.com/spreadsheets/d/{ss.id}"


# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor 3.5")
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
            
            # FILTER
            merged_df = merged_df[merged_df["Student Name"].str.strip().astype(bool)]
            
            # FILL
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            # ABBREVIATE NAMES
            merged_df["Class Name"] = merged_df["Class Name"].apply(abbreviate_class_name)
            
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
