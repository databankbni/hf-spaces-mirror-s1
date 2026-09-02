"""
General Resume Parser - Industrial Grade
Handles multiple resume formats using hybrid approach
"""

import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dateutil import parser as dateparser
import spacy

# Load spaCy model
try:
    nlp = spacy.load("en_core_web_lg")
except OSError:
    import subprocess
    subprocess.run(["python", "-m", "spacy", "download", "en_core_web_lg"])
    nlp = spacy.load("en_core_web_lg")


# ===================================================================
# TEXT EXTRACTION
# ===================================================================
def _extract_text(file_bytes: bytes, filename: str | None) -> str:
    """Extract text from PDF or DOCX files."""
    filename = (filename or "").lower()
    
    try:
        import io
        
        if filename.endswith(".pdf") or file_bytes[:4] == b"%PDF":
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                return _clean_text("\n".join(pages))
            except Exception as e:
                print(f"PDF extraction error: {e}")
                return ""
        
        if filename.endswith(".docx") or file_bytes[:2] == b"PK":
            try:
                from io import BytesIO
                from docx import Document
                doc = Document(BytesIO(file_bytes))
                paragraphs = [p.text for p in doc.paragraphs]
                return _clean_text("\n".join(paragraphs))
            except Exception as e:
                print(f"DOCX extraction error: {e}")
                return ""
    except Exception as e:
        print(f"General extraction error: {e}")
    
    try:
        return _clean_text(file_bytes.decode("utf-8", errors="ignore"))
    except Exception:
        return ""


def _clean_text(text: str) -> str:
    """Clean and normalize text."""
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = text.replace("–", "--")  # Normalize em-dash
    text = text.replace("—", "--")  # Normalize long dash
    text = re.sub(r"[\r\t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


# ===================================================================
# FORMAT DETECTION
# ===================================================================
def _detect_format(text: str) -> str:
    """
    Detect resume format:
    - 'standard': Company -- Position | Date
    - 'simple': Company\nPosition Date
    - 'bullet': Heavy use of bullet points
    """
    # Check for standard format with dashes and pipes
    if re.search(r'[A-Z][^\n]+--[^\n]+\|', text):
        return 'standard'
    
    # Check for simple format (company on one line, position on next)
    date_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}'
    lines = text.split('\n')[:50]
    
    simple_count = 0
    for i, line in enumerate(lines):
        if i + 1 < len(lines):
            if re.search(date_pattern, lines[i + 1], re.IGNORECASE):
                simple_count += 1
    
    if simple_count >= 2:
        return 'simple'
    
    # Default to bullet format
    return 'bullet'


# ===================================================================
# SECTION SPLITTING
# ===================================================================
def _split_into_sections(text: str) -> Dict[str, str]:
    """Split resume into major sections using flexible patterns."""
    sections = {}
    
    section_patterns = {
        'summary': r'(?:^|\n)(SUMMARY|PROFESSIONAL SUMMARY|EXECUTIVE SUMMARY|PROFILE|OBJECTIVE|ABOUT ME)\s*$',
        'experience': r'(?:^|\n)(WORK\s+)?EXPERIENCE|EMPLOYMENT HISTORY|PROFESSIONAL EXPERIENCE\s*$',
        'education': r'(?:^|\n)EDUCATION|ACADEMIC BACKGROUND|QUALIFICATIONS?\s*$',
        'skills': r'(?:^|\n)SKILLS?|TECHNICAL SKILLS?|COMPETENCIES|SKILLS & INTERESTS\s*$',
        'projects': r'(?:^|\n)PROJECTS?|PROJECT EXPERIENCE\s*$',
        'achievements': r'(?:^|\n)ACHIEVEMENTS?|AWARDS?|HONORS?\s*$',
        'certificates': r'(?:^|\n)CERTIFICATES?|CERTIFICATIONS?\s*$',
    }
    
    section_positions = []
    for section_name, pattern in section_patterns.items():
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            section_positions.append((match.start(), section_name, match.end()))
    
    section_positions.sort()
    
    for i, (start, name, header_end) in enumerate(section_positions):
        if i + 1 < len(section_positions):
            end = section_positions[i + 1][0]
        else:
            end = len(text)
        
        sections[name] = text[header_end:end].strip()
    
    return sections


# ===================================================================
# CONTACT INFORMATION
# ===================================================================
def _extract_contact_info(text: str) -> Dict[str, Optional[str]]:
    """Extract all contact information."""
    # Get first 500 chars for contact info
    header = text[:500]
    
    # Email
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email = re.search(email_pattern, header, re.IGNORECASE)
    
    # Phone - multiple patterns
    phone_patterns = [
        r'\+\d{1,3}[\s-]?\d{3}[\s-]?\d{7,10}',
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        r'Phone.*?(\+?\d[\d\s-]{9,})',
    ]
    phone = None
    for pattern in phone_patterns:
        match = re.search(pattern, header, re.IGNORECASE)
        if match:
            phone = match.group(1) if match.lastindex else match.group(0)
            phone = re.sub(r'\s+', ' ', phone.strip())
            break
    
    # Name - usually first non-empty line
    lines = text.split('\n')
    name = None
    for line in lines[:5]:
        line = line.strip()
        if line and '@' not in line and 'http' not in line.lower():
            words = line.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                if not any(kw in line.lower() for kw in ['resume', 'cv', 'curriculum']):
                    name = line
                    break
    
    # Location - use NER
    doc = nlp(header)
    location = None
    for ent in doc.ents:
        if ent.label_ in ["GPE", "LOC"]:
            # Make sure it's not the name
            if name and ent.text not in name:
                location = ent.text
                break
    
    return {
        'name': name,
        'email': email.group(0) if email else None,
        'phone': phone,
        'location': location
    }


# ===================================================================
# SKILLS EXTRACTION
# ===================================================================
def _extract_skills(text: str, sections: Dict[str, str]) -> List[str]:
    """Extract technical skills using patterns and NLP."""
    skills = set()
    
    # Get skills section if available
    skills_text = sections.get('skills', text)
    
    # Comprehensive skill patterns
    skill_patterns = [
        r'\b(Python|Java|JavaScript|TypeScript|C\+\+|C#|Ruby|Go|Rust|PHP|Swift|Kotlin|Scala|Dart|R|Perl)\b',
        r'\b(React(?:JS)?|Angular|Vue(?:\.js)?|Next(?:\.js)?|Node(?:JS)?|Express(?:JS)?|Django|Flask|FastAPI|Spring)\b',
        r'\b(MongoDB|PostgreSQL|MySQL|Redis|Oracle|SQL Server|DynamoDB|Firebase|Supabase|Cassandra)\b',
        r'\b(AWS|Azure|GCP|Docker|Kubernetes|Jenkins|CI/CD|Terraform|Ansible|Git|GitHub)\b',
        r'\b(TensorFlow|PyTorch|Pandas|NumPy|Scikit-learn|Keras|OpenAI|NLP|Machine Learning|ML|AI)\b',
        r'\b(REST|GraphQL|Microservices|Agile|Scrum|JIRA|Linux|Unix)\b',
    ]
    
    for pattern in skill_patterns:
        matches = re.findall(pattern, skills_text, re.IGNORECASE)
        skills.update(matches)
    
    # Parse structured skills (Category: skill1, skill2)
    category_pattern = r'(?:^|\n)([A-Za-z\s/&]+):\s*([^\n]+)'
    for match in re.finditer(category_pattern, skills_text, re.MULTILINE):
        skill_list = match.group(2)
        items = re.split(r'[,|]', skill_list)
        for item in items:
            item = item.strip()
            item = re.sub(r'\([^)]*\)', '', item).strip()  # Remove (learning), etc.
            if item and 2 <= len(item) <= 40:
                skills.add(item)
    
    return sorted(list(skills), key=str.lower)


# ===================================================================
# EXPERIENCE EXTRACTION - MULTI-FORMAT
# ===================================================================
def _extract_experience_standard(exp_text: str) -> List[Dict[str, Any]]:
    """Extract experience in standard format: Company -- Position | Date"""
    experiences = []
    lines = exp_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        if '--' in line and '|' in line:
            match = re.match(r'^(.+?)\s*--\s*(.+?)\s*\|\s*(.+?)(?:,\s*(.+?))?$', line)
            
            if match:
                company = match.group(1).strip()
                position = match.group(2).strip()
                date_range = match.group(3).strip()
                location = match.group(4).strip() if match.group(4) else None
                
                start_date, end_date = _extract_dates_from_range(date_range)
                
                # Collect description
                description_lines = []
                i += 1
                while i < len(lines):
                    desc_line = lines[i].strip()
                    if not desc_line:
                        i += 1
                        continue
                    if ('--' in desc_line and '|' in desc_line):
                        break
                    desc_line = re.sub(r'^[-•*]\s*', '', desc_line)
                    description_lines.append(desc_line)
                    i += 1
                
                experiences.append({
                    "company": company,
                    "position": position,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "description": '\n'.join(description_lines) if description_lines else None,
                    **_calculate_duration(start_date, end_date)
                })
                continue
        i += 1
    
    return experiences


def _extract_experience_simple(exp_text: str) -> List[Dict[str, Any]]:
    """Extract experience in simple format: Company\nPosition Date"""
    experiences = []
    lines = exp_text.split('\n')
    i = 0
    
    date_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s*-\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Present)\s*\d{0,4}'
    
    while i < len(lines):
        line = lines[i].strip()
        
        if line and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            
            # Check if next line has date
            if re.search(date_pattern, next_line, re.IGNORECASE):
                company = line
                
                # Parse position and date
                pos_match = re.match(r'^(.+?)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', next_line, re.IGNORECASE)
                if pos_match:
                    position = pos_match.group(1).strip()
                    date_match = re.search(date_pattern, next_line, re.IGNORECASE)
                    date_range = date_match.group(0) if date_match else ""
                    
                    start_date, end_date = _extract_dates_from_range(date_range)
                    
                    # Collect description
                    description_lines = []
                    i += 2
                    while i < len(lines):
                        desc_line = lines[i].strip()
                        if not desc_line:
                            i += 1
                            continue
                        # Stop if next line looks like another job
                        if i + 1 < len(lines) and re.search(date_pattern, lines[i + 1], re.IGNORECASE):
                            break
                        desc_line = re.sub(r'^[-•*]\s*', '', desc_line)
                        description_lines.append(desc_line)
                        i += 1
                    
                    experiences.append({
                        "company": company,
                        "position": position,
                        "start_date": start_date,
                        "end_date": end_date,
                        "location": None,
                        "description": '\n'.join(description_lines) if description_lines else None,
                        **_calculate_duration(start_date, end_date)
                    })
                    continue
        i += 1
    
    return experiences


def _extract_experience(text: str, sections: Dict[str, str], format_type: str) -> List[Dict[str, Any]]:
    """Extract experience using appropriate parser based on format."""
    exp_text = sections.get('experience', '')
    
    if not exp_text or len(exp_text) < 10:
        return []
    
    if format_type == 'standard':
        return _extract_experience_standard(exp_text)
    elif format_type == 'simple':
        return _extract_experience_simple(exp_text)
    else:
        # Try both and return whichever gives more results
        standard = _extract_experience_standard(exp_text)
        simple = _extract_experience_simple(exp_text)
        return standard if len(standard) >= len(simple) else simple


# ===================================================================
# EDUCATION EXTRACTION - MULTI-FORMAT
# ===================================================================
def _extract_education(text: str, sections: Dict[str, str]) -> List[Dict[str, Any]]:
    """Extract education entries - handles multiple formats."""
    education = []
    edu_text = sections.get('education', '')
    
    if not edu_text or len(edu_text) < 10:
        return []
    
    lines = edu_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Format 1: Institution -- Degree | Date
        if '--' in line:
            match = re.match(r'^(.+?)\s*--\s*(.+?)(?:\s*\|\s*(.+?))?$', line)
            if match:
                institution = match.group(1).strip()
                degree = match.group(2).strip()
                date_info = match.group(3).strip() if match.group(3) else ""
                
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.search(r'(?:GPA|CGPA)', next_line, re.IGNORECASE):
                        date_info = date_info + " " + next_line
                        i += 1
                
                dates = re.findall(r'\b(20\d{2}|19\d{2})\b', date_info)
                gpa_match = re.search(r'(?:GPA|CGPA)[:\s]*([\d.]+(?:\s*/\s*[\d.]+)?)', date_info, re.IGNORECASE)
                
                education.append({
                    "institution": institution,
                    "degree": degree,
                    "start_date": dates[0] if len(dates) > 0 else None,
                    "end_date": dates[1] if len(dates) > 1 else None,
                    "gpa": gpa_match.group(1) if gpa_match else None
                })
                i += 1
                continue
        
        # Format 2: Institution\nDegree Date
        if line and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            
            # Check if next line has degree keywords
            degree_keywords = ['bachelor', 'master', 'phd', 'computer science', 'engineering', 'graduation date']
            if any(kw in next_line.lower() for kw in degree_keywords):
                institution = line
                
                # Extract degree
                degree_match = re.match(r'^(.+?)(?:\s+Graduation Date:|\s+\d{4})', next_line, re.IGNORECASE)
                degree = degree_match.group(1).strip() if degree_match else next_line.split('Graduation Date:')[0].strip()
                
                dates = re.findall(r'\b(20\d{2}|19\d{2})\b', next_line)
                
                # Check for GPA on next line
                gpa = None
                if i + 2 < len(lines):
                    gpa_line = lines[i + 2].strip()
                    gpa_match = re.search(r'(?:GPA|CGPA)[:\s]*([\d.]+(?:\s*/\s*[\d.]+)?)', gpa_line, re.IGNORECASE)
                    if gpa_match:
                        gpa = gpa_match.group(1)
                
                education.append({
                    "institution": institution,
                    "degree": degree,
                    "start_date": None,
                    "end_date": dates[0] if len(dates) > 0 else None,
                    "gpa": gpa
                })
                i += 2
                continue
        
        i += 1
    
    return education


# ===================================================================
# DATE PARSING
# ===================================================================
def _extract_dates_from_range(date_str: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract start and end dates from a date range string."""
    date_str = date_str.strip()
    date_str = re.sub(r'\s*(?:--|-|to|–)\s*', '|', date_str, flags=re.IGNORECASE)
    
    parts = date_str.split('|')
    start_date = parts[0].strip() if len(parts) > 0 else None
    end_date = parts[1].strip() if len(parts) > 1 else None
    
    if end_date and re.search(r'\b(present|current)\b', end_date, re.IGNORECASE):
        end_date = "Present"
    
    return start_date, end_date


def _parse_date(value: Any) -> Optional[datetime]:
    """Parse date string to datetime object."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.lower() in ['present', 'current']:
        return datetime.utcnow()
    try:
        return dateparser.parse(str(value))
    except Exception:
        return None


def _calculate_duration(start_date: Any, end_date: Any) -> Dict[str, Any]:
    """Calculate duration between dates."""
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date) or datetime.utcnow()
    
    if not start_dt or not end_dt:
        return {"duration_days": None, "duration_years": None, "duration_str": None}
    
    delta_days = max(0, (end_dt - start_dt).days)
    duration_years = delta_days / 365.25
    
    years = delta_days // 365
    months = (delta_days % 365) // 30
    
    if years > 0:
        duration_str = f"{years}y{f' {months}m' if months else ''}"
    elif months > 0:
        duration_str = f"{months}m"
    else:
        duration_str = f"{max(1, delta_days)}d"
    
    return {
        "duration_days": delta_days,
        "duration_years": round(duration_years, 2),
        "duration_str": duration_str
    }


# ===================================================================
# SUMMARY & HEADLINE
# ===================================================================
def _extract_summary(sections: Dict[str, str]) -> str:
    """Extract professional summary."""
    summary = sections.get('summary', '')
    summary = re.sub(r'https?://[^\s]+', '', summary)
    summary = re.sub(r'LinkedIn Profile:.*?(?=\n|$)', '', summary, flags=re.IGNORECASE)
    summary = re.sub(r'GitHub Profile:.*?(?=\n|$)', '', summary, flags=re.IGNORECASE)
    return summary.strip()


def _infer_headline(summary: str, skills: List[str], experiences: List[Dict]) -> str:
    """Infer professional headline."""
    if experiences:
        title = experiences[0].get("position", "")
        title = re.sub(r'\s*\([^)]*\)', '', title)
        title = title.replace(" Intern", "").strip()
        if title:
            return title
    
    pool = " ".join([summary, " ".join(skills)]).lower()
    
    role_keywords = {
        "Full Stack Developer": r"full[- ]?stack",
        "AI/ML Engineer": r"ai.*engineer|machine learning.*engineer|ml.*engineer",
        "Data Engineer": r"data engineer",
        "Software Engineer": r"software engineer|software developer",
        "DevOps Engineer": r"devops|sre",
        "Backend Developer": r"backend.*developer",
        "Frontend Developer": r"frontend.*developer",
    }
    
    for role, pattern in role_keywords.items():
        if re.search(pattern, pool, re.IGNORECASE):
            return role
    
    return "Software Engineer"


# ===================================================================
# MAIN PARSER
# ===================================================================
def parse_resume_file(
    file_bytes: bytes,
    filename: str | None = None
) -> Dict[str, Any]:
    """
    General-purpose resume parser that handles multiple formats.
    Returns a dictionary with parsed resume data or error information.
    """
    # Extract text
    text = _extract_text(file_bytes, filename)
    
    if not text or len(text) < 100:
        return {"error": "Could not extract sufficient text from resume"}
    
    print(f"Extracted {len(text)} characters from resume")
    
    # Detect format
    format_type = _detect_format(text)
    print(f"Detected format: {format_type}")
    
    # Split into sections
    sections = _split_into_sections(text)
    print(f"Found sections: {list(sections.keys())}")
    
    # Extract contact information
    contact = _extract_contact_info(text)
    
    # Extract main sections
    skills = _extract_skills(text, sections)
    experiences = _extract_experience(text, sections, format_type)
    education = _extract_education(text, sections)
    summary = _extract_summary(sections)
    
    # Calculate total experience
    total_days = sum(exp.get("duration_days", 0) or 0 for exp in experiences)
    total_years = total_days / 365.25 if total_days else 0
    total_experience = f"{int(total_years)}+ years" if total_years >= 1 else "<1 year"
    
    # Infer headline
    headline = _infer_headline(summary, skills, experiences)
    primary_title = experiences[0].get("position") if experiences else None
    
    # Build result
    result = {
        "name": contact['name'],
        "email": contact['email'],
        "phone": contact['phone'],
        "headline": headline,
        "primary_title": primary_title,
        "total_experience": total_experience,
        "total_experience_years": round(total_years, 2),
        "location": contact['location'],
        "summary": summary,
        "skills": skills,
        "experience": experiences,
        "education": education,
        "format_detected": format_type
    }
    
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
    return result


def _names_match(name1: str, name2: str) -> bool:
    """Fuzzy name matching."""
    if not name1 or not name2:
        return False
    
    n1 = re.sub(r'[^\w\s]', '', name1.lower()).split()
    n2 = re.sub(r'[^\w\s]', '', name2.lower()).split()
    
    matches = len(set(n1) & set(n2))
    return matches >= 2 or (matches >= 1 and len(n1) <= 2)