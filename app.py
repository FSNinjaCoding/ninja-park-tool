import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

# VERSION UPDATE: 3.8
st.set_page_config(page_title="Ninja Park Processor 3.8", layout="wide")

# --- HELPER FUNCTIONS ---

def clean_name(name):
    """Standardizes names (Title Case, no extra spaces)."""
    if not isinstance(name, str): return ""
    clean = re.sub(r'\s+', ' ', name).replace(u'\xa0', ' ').strip()
    return clean.title()

def abbreviate_class_name(name):
    """Shortens class names to save space."""
    if not isinstance(name, str): return name
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
        st.warning("⚠️ Formatting warning: Could not find standard class headers.")

    for header in headers:
        name_span = header.find('span')
        class_name_raw = name_span.get_text(strip=True) if name_span else header.get_text(separator=" ", strip=True)
        current_class_name = class_name_raw if class_name_raw else "Unknown Class"
        
        table = header.find_next('table', class_='table-roll-sheet')
        next_header = header.find_next('div', class_='full-width-header')
        
        if table and next_header:
            h_line = next_header.sourceline
            t_line = table.sourceline
            if h_line is not None and t_line is not None and h_line < t_line:
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

# --- FORMATTING & STRUCTURE ---

def apply_highlight_rules(df_records):
    formats = [None] * len(df_records)
    
    # 1. BASE RULES
    for i, row in enumerate(df_records):
        student_name = row.get("Student Name", "")
        # IGNORE "open" rows and blank rows
        if not student_name or student_name == "open": continue
        
        if "ignore" in str(row.get("RS Comment", "")).lower(): continue
            
        skill = parse_skill_number(row.get("Level", "0"))
        group = parse_group_number(row.get("Keyword", "99"))
        class_name = str(row.get("Class Name", "")).lower()
        is_advanced = "advanced" in class_name
        
        # RED TEXT (Bold + Red Text)
        if not is_advanced and skill >= 3:
            formats[i] = {"text_color": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}
            continue

        # LIGHT RED BG (Blank Group)
        if group == 99:
            formats[i] = {"bg": {"red": 1.0, "green": 0.8, "blue": 0.8}, "bold": False}
            continue

        # YELLOW BG
        is_yellow = False
        if is_advanced:
            if group == 1 and skill >= 5: is_yellow = True
            elif group == 2 and skill >= 7: is_yellow = True
            elif group == 3 and skill == 3: is_yellow = True
        else:
            if group == 1 and skill >= 2: is_yellow = True
            elif group == 2 and skill == 0: is_yellow = True
            elif group == 3 and skill <= 1: is_yellow = True
            
        if is_yellow:
            formats[i] = {"bg": {"red": 1.0, "green": 0.95, "blue": 0.8}, "bold": False}
            continue

    # 2. GREEN RULE (Move Up)
    def apply_green_recursive(indices):
        if not indices: return
        for idx in reversed(indices):
            row_comment = str(df_records[idx].get("RS Comment", "")).lower()
            if "ignore" in row_comment: continue
            
            # Skip "open" rows for green highlighting logic
            if df_records[idx].get("Student Name") == "open": continue

            if formats[idx] is None:
                formats[idx] = {"bg": {"red": 0.85, "green": 0.92, "blue": 0.83}, "bold": False}
                break 

    group_1_indices = [i for i, r in enumerate(df_records) if parse_group_number(r.get("Keyword", "")) == 1]
    group_2_indices = [i for i, r in enumerate(df_records) if parse_group_number(r.get("Keyword", "")) == 2]

    apply_green_recursive(group_1_indices)
    apply_green_recursive(group_2_indices)

    return formats

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

    full_df = full_df.rename(columns={
        "Attendance": "Attend#",
        "Student Keyword": "Keyword",
        "Skill Level": "Level",
        "Roll Sheet Comment": "RS Comment"
    })

    days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Lost"]
    export_cols = ["Student Name", "Age", "Attend#", "Keyword", "Level", "Class Name", "RS Comment"]

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

        try:
            old_ws = ss.worksheet(day)
            ss.del_worksheet(old_ws)
        except: pass 

        unique_times = sorted(day_df['Sort Time'].unique())
        slot_data_map = {}
        slot_format_map = {}
        slot_border_ranges = {} 
        max_rows = 0
        
        # --- BUILD STRUCTURE PER TIME SLOT ---
        for i, time_slot in enumerate(unique_times):
            time_df = day_df[day_df['Sort Time'] == time_slot].copy()
            
            # Helper to sort
            def get_sorted_group(grp_num):
                mask = time_df['Keyword'].apply(lambda x: parse_group_number(x) == grp_num)
                grp_df = time_df[mask].copy()
                
                grp_df['sort_skill'] = grp_df['Level'].apply(parse_skill_number)
                grp_df['sort_att'] = grp_df['Attend#'].apply(parse_attendance)
                grp_df['sort_age'] = grp_df['Age'].apply(parse_age)
                
                return grp_df.sort_values(
                    by=['sort_skill', 'sort_att', 'sort_age'],
                    ascending=[True, True, True]
                )

            g1 = get_sorted_group(1)
            g2 = get_sorted_group(2)
            g3 = get_sorted_group(3)
            g_other = time_df[~time_df.index.isin(g1.index.union(g2.index).union(g3.index))].copy()

            final_records = []
            border_ranges = []
            
            # Helper to Pad and Append
            def add_group_block(df_group, label_num):
                nonlocal final_records, border_ranges
                
                rows = df_group.to_dict('records')
                count = len(rows)
                
                needed = max(0, 7 - count)
                
                open_rows = []
                for _ in range(needed):
                    open_rows.append({
                        "Student Name": "open",
                        "Age": "", "Attend#": "", 
                        "Keyword": "",   # BLANK for open rows
                        "Level": "",     # BLANK for open rows
                        "Class Name": "",# BLANK for open rows
                        "RS Comment": ""
                    })
                
                block = open_rows + rows
                
                start_idx = len(final_records) 
                end_idx = start_idx + len(block) - 1
                
                border_ranges.append((start_idx, end_idx))
                final_records.extend(block)
                
                spacer = {c: "" for c in export_cols}
                final_records.extend([spacer])

            # Build the Stack
            add_group_block(g1, 1)
            add_group_block(g2, 2)
            add_group_block(g3, 3)
            
            if not g_other.empty:
                final_records.extend(g_other.to_dict('records'))

            # Store Data
            formats_list = apply_highlight_rules(final_records)
            slot_format_map[i] = formats_list
            slot_border_ranges[i] = border_ranges
            
            final_block = pd.DataFrame(final_records)
            if final_block.empty: final_block = pd.DataFrame(columns=export_cols)
            else: final_block = final_block[export_cols]

            slot_data_map[i] = final_block
            if len(final_block) > max_rows: max_rows = len(final_block)

        # --- GRID CONSTRUCTION ---
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
                    row_data.extend(df.iloc[r][export_cols].tolist())
                else:
                    row_data.extend([""] * len(export_cols))
                row_data.append("")
            final_values.append(row_data)

        total_cols = max(len(unique_times) * 8, 26) 
        total_rows = len(final_values) + 20 
        ws = ss.add_worksheet(title=day, rows=total_rows, cols=total_cols)
        ws.update(range_name="A1", values=final_values)
        
        requests = []
        
        # 1. BOLD HEADERS (Row 1)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": total_cols
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"
            }
        })
        
        # 2. FORMATTING (Colors/Text) & BORDERS
        current_col_start = 0
        for i in range(len(unique_times)):
            # A. Colors/Text
            formats = slot_format_map[i]
            for row_idx, fmt in enumerate(formats):
                if fmt:
                    sheet_row_index = row_idx + 1 
                    cell_format = {}
                    fields_list = []
                    
                    if "bg" in fmt:
                        cell_format["backgroundColor"] = fmt["bg"]
                        fields_list.append("userEnteredFormat.backgroundColor")
                    
                    text_fmt = {}
                    if "bold" in fmt: text_fmt["bold"] = fmt["bold"]
                    if "text_color" in fmt: text_fmt["foregroundColor"] = fmt["text_color"]
                    
                    if text_fmt:
                        cell_format["textFormat"] = text_fmt
                        fields_list.append("userEnteredFormat.textFormat")

                    if fields_list:
                        requests.append({
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": sheet_row_index, "endRowIndex": sheet_row_index + 1,
                                    "startColumnIndex": current_col_start, "endColumnIndex": current_col_start + len(export_cols)
                                },
                                "cell": {"userEnteredFormat": cell_format},
                                "fields": ",".join(fields_list)
                            }
                        })
            
            # B. Borders
            ranges = slot_border_ranges[i]
            for (start_r, end_r) in ranges:
                sheet_start_row = start_r + 1 
                sheet_end_row = end_r + 2 
                
                requests.append({
                    "updateBorders": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": sheet_start_row,
                            "endRowIndex": sheet_end_row,
                            "startColumnIndex": current_col_start,
                            "endColumnIndex": current_col_start + len(export_cols)
                        },
                        "top": {"style": "SOLID", "width": 1},
                        "bottom": {"style": "SOLID", "width": 1},
                        "left": {"style": "SOLID", "width": 1},
                        "right": {"style": "SOLID", "width": 1}
                    }
                })

            current_col_start += (len(export_cols) + 1)

        # 3. Auto-Fit
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": total_cols}
            }
        })

        if requests:
            ss.batch_update({"requests": requests})

    return f"https://docs.google.com/spreadsheets/d/{ss.id}"


# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor 3.8")
st.write("Dashboard Layout: 7-Row Groups with Borders")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

if roll_file and list_file:
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Building Dashboard...'):
        try:
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())

            if df_roll.empty: st.warning("⚠️ No data in Roll Sheet.")
            if df_list.empty: st.warning("⚠️ No data in Student List.")

            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            merged_df = merged_df[merged_df["Student Name"].str.strip().astype(bool)]
            
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
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
