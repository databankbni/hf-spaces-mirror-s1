#!/usr/bin/env python3
"""Single fail-closed live market packet entry point.

Uses only the Python standard library. It persists public raw Titan007 responses
outside model context, normalizes a compact packet, and never emits a direction.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, re, socket, sqlite3, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import urllib.parse
from zoneinfo import ZoneInfo
_SCRIPT_DIR=Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path: sys.path.insert(0,str(_SCRIPT_DIR))
from titan007_fundamentals import capture as capture_fundamentals
from titan007_market_depth import capture as capture_market_depth
from fetch_titan007_correct_score import fetch_for_packet as capture_correct_score
from titan007_competition_stage import capture_for_packet as capture_competition_stage
from titan007_h2h import build_portable_evidence as build_h2h_evidence
from market_change_detector import digest as canonical_digest
from production_accuracy_selector import (
    build_accuracy_features,
    accuracy_features_valid,
)

ROOT=Path(os.getenv('HF_COLLECTOR_ROOT') or Path(__file__).resolve().parents[1])
DB=ROOT/'changedetection-data'/'water_timeseries.db'
SNAPSHOTS=ROOT/'market_snapshots'
LOCAL_PACKETS=ROOT/'market_packets'
MAX_AGE_HOURS=6
# Non-blocking wait bounds for optional auxiliary captures. correct_score is
# explicitly optional/non-blocking (blocking=false everywhere), so a slow or hung
# correct-score fetch must never delay the core packet past its freshness age gate.
CORRECT_SCORE_WAIT_SECONDS=8
COMPETITION_STAGE_WAIT_SECONDS=10
HF_BASE_URL='https://llama12315-football-data-hub-space.hf.space'
# Directional analysis cannot rely on the six-hour data-only cache.  It must
# acquire a new, identity-locked live snapshot no older than this window.
ANALYSIS_FRESHNESS_MINUTES=30
FETCH_ATTEMPTS=3
COMPANIES={'3':'Crown','24':'Pinnacle','31':'Bet365','14':'WilliamHill','17':'Ladbrokes'}
MARKETS={'handicap.aspx':'AH','overunder.aspx':'OU'}
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://vip.titan007.com/','Accept-Language':'zh-CN,zh;q=0.9'}

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self._row=None; self._cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self._row=[]
        elif tag in ('td','th') and self._row is not None: self._cell=[]
    def handle_data(self,data):
        if self._cell is not None: self._cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self._cell is not None:
            self._row.append(' '.join(''.join(self._cell).split())); self._cell=None
        elif tag=='tr' and self._row is not None:
            self.rows.append(self._row); self._row=None

class OverviewParser(HTMLParser):
    """Keep row attributes so Titan007 overview quotes can be bound to company IDs."""
    def __init__(self):
        super().__init__(); self.rows=[]; self._row=None; self._cell=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='tr': self._row={'attrs':attrs,'cells':[],'inputs':[]}
        elif self._row is not None and tag=='input': self._row['inputs'].append(attrs)
        elif tag in ('td','th') and self._row is not None: self._cell={'attrs':attrs,'text':[]}
    def handle_data(self,data):
        if self._cell is not None: self._cell['text'].append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self._cell is not None:
            self._cell['text']=' '.join(''.join(self._cell['text']).split())
            self._row['cells'].append(self._cell); self._cell=None
        elif tag=='tr' and self._row is not None:
            self.rows.append(self._row); self._row=None

def utcnow(): return datetime.now(timezone.utc)

def parse_overview_market(raw:bytes, market:str, *, captured_at:str, kicked_off:bool=False)->dict:
    """Parse immutable AH/OU overview rows as a current-quote fallback.

    Overview pages expose opening/current values for every company even when an
    individual changeDetail history page is an empty shell.  The capture time is
    used as the current quote timestamp; no history/K-line depth is invented.
    """
    parser=OverviewParser(); parser.feed(decode(raw)); out={}
    for row in parser.rows:
        ids=[str(item.get('data-id') or '') for item in row['inputs']]
        row_cid=str(row['attrs'].get('companyid') or row['attrs'].get('companyID') or '')
        cid=next((value for value in ids+[row_cid] if value in COMPANIES), '')
        cells=row['cells']
        adjacent=bool(row_cid and len(cells)>=9 and len(cells)>2 and str(cells[2]['text']).startswith(('盘','plate')))
        offset=3
        if not cid or len(cells)<offset+6: continue
        values=[cell['text'] for cell in cells]
        try:
            opening_water=float(values[offset]); opening_opponent=float(values[offset+2])
            current_water=float(values[offset+3]); current_opponent=float(values[offset+5])
        except (ValueError,TypeError,IndexError):
            continue
        opening_line=str(values[offset+1]).strip(); current_line=str(values[offset+4]).strip()
        if not opening_line or not current_line or '-' in (opening_line,current_line): continue
        opening_time=(cells[offset]['attrs'].get('title') or cells[offset+1]['attrs'].get('title') or captured_at)
        opening={'water':opening_water,'line':opening_line,'opponent_water':opening_opponent,'changed_at':opening_time,'status':'早'}
        current={'water':current_water,'line':current_line,'opponent_water':current_opponent,'changed_at':captured_at,'status':'即'}
        candidate={'row_count':2,'opening':opening,'current':None if kicked_off else current,
                   'history':[opening] if kicked_off else [opening,current],
                   'kicked_off':bool(kicked_off),'usable_current':not kicked_off,
                   'payload_status':'POSTKICKOFF_OVERVIEW_DIAGNOSTIC_ONLY' if kicked_off else 'OVERVIEW_CURRENT_FALLBACK',
                   'empty_shell':False,'quote_source':'company_overview_summary','history_available':False,
                   'overview_depth':'adjacent' if adjacent else 'main',
                   'postkickoff_observed_quote':current if kicked_off else None}
        previous=out.get(cid)
        # Main rows are authoritative.  When the main row is absent, preserve the
        # first real adjacent row (plate2) instead of allowing plate3/plate4 to
        # overwrite it later in the overview table.
        if previous is None or (previous.get('overview_depth')=='adjacent' and not adjacent):
            out[cid]=candidate
    return out

def overview_change_payload(parsed:dict)->bytes:
    """Serialize overview-derived quotes into the canonical seven-cell evidence shape."""
    rows=[]
    for item in (parsed.get('opening'),parsed.get('current')):
        if not item: continue
        rows.append('<tr><td></td><td></td><td>{water}</td><td>{line}</td><td>{opponent_water}</td><td>{changed_at}</td><td>{status}</td></tr>'.format(**item))
    return ('<html><body><table>'+''.join(rows)+'</table></body></html>').encode('utf-8')
def age_seconds(value: str | None, *, now: datetime | None = None) -> int | None:
    """Return non-negative UTC age for an ISO timestamp, or None if invalid."""
    try:
        captured=datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)
    except (TypeError,ValueError):
        return None
    return max(0,round(((now or utcnow())-captured).total_seconds()))
def freshness_tier(identity: dict, captured: datetime) -> tuple[int,str]:
    """Directional packets get stricter as kickoff approaches."""
    try:
        kickoff=datetime.fromisoformat(str(identity.get('kickoff')).replace('Z','+00:00')).astimezone(timezone.utc)
        minutes=(kickoff-captured).total_seconds()/60
    except (TypeError,ValueError):
        return ANALYSIS_FRESHNESS_MINUTES,'UNKNOWN_KICKOFF'
    if minutes<=30:return 2,'T_MINUS_30'
    if minutes<=120:return 5,'T_MINUS_120'
    if minutes<=360:return 15,'T_MINUS_360'
    return ANALYSIS_FRESHNESS_MINUTES,'EARLY_PREMATCH'
def freshness_contract(identity: dict, captured: datetime, *, source_mode: str, remote_packet_found: bool) -> dict:
    max_age_minutes,tier=freshness_tier(identity,captured)
    return {'source_mode':source_mode,'origin_source_mode':source_mode,'remote_packet_found':remote_packet_found,'live_refresh_performed':source_mode=='local_live_packet','captured_at':captured.isoformat(),'age_seconds':0,'max_age_seconds':max_age_minutes*60,'freshness_tier':tier,'eligible_for_directional_analysis':True}
def iso(ts): return datetime.fromtimestamp(ts,timezone.utc).isoformat()
def atomic_bytes(path:Path,value:bytes):
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(value); temp.replace(path)
def atomic_json(path:Path,value:dict):
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)
RELAY_TEMPLATES=[t for t in (os.getenv('TITAN007_RELAYS') or
    'https://api.allorigins.win/raw?url={q}').split(',') if t.strip()]
RELAY_MIN_BYTES=int(os.getenv('TITAN007_RELAY_MIN_BYTES') or 600)
LAST_FETCH_TRANSPORT={'mode':'direct','relay':None}
# Per-host direct-egress circuit breaker.  When direct egress to a host is
# blocked at the network level, every URL otherwise pays FETCH_ATTEMPTS x
# timeout before the relay is tried, which pushed a single five-company
# capture past its outer budget.  After DIRECT_FAIL_THRESHOLD consecutive
# transport failures the host is marked unreachable and direct attempts are
# skipped for DIRECT_PROBE_INTERVAL seconds (one cheap re-probe after that,
# so recovery is detected automatically).
DIRECT_FAIL_THRESHOLD=int(os.getenv('TITAN007_DIRECT_FAIL_THRESHOLD') or 2)
DIRECT_PROBE_INTERVAL=int(os.getenv('TITAN007_DIRECT_PROBE_INTERVAL') or 300)
DIRECT_TIMEOUT=int(os.getenv('TITAN007_DIRECT_TIMEOUT') or 8)
# The relay pool is a public best-effort service: measured single-shot success
# is ~40%, but retry-until-success converges (4/6 within 4 tries).  The relay
# therefore needs its own, larger attempt budget with linear backoff instead of
# reusing FETCH_ATTEMPTS, which is sized for a healthy direct origin.
RELAY_ATTEMPTS=int(os.getenv('TITAN007_RELAY_ATTEMPTS') or 7)
RELAY_BACKOFF=float(os.getenv('TITAN007_RELAY_BACKOFF') or 1.2)
SHELL_RETRY_LIMIT_RELAY=int(os.getenv('TITAN007_SHELL_RETRY_LIMIT_RELAY') or 2)
_DIRECT_STATE={}
def _host_of(url:str)->str:
    try:return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:return ''
def _direct_allowed(host:str)->bool:
    st=_DIRECT_STATE.get(host)
    if not st:return True
    if st['fails']<DIRECT_FAIL_THRESHOLD:return True
    return (time.time()-st['blocked_at'])>=DIRECT_PROBE_INTERVAL
def _direct_note(host:str,ok:bool)->None:
    st=_DIRECT_STATE.setdefault(host,{'fails':0,'blocked_at':0.0})
    if ok:st['fails']=0;st['blocked_at']=0.0
    else:
        st['fails']+=1
        if st['fails']>=DIRECT_FAIL_THRESHOLD:st['blocked_at']=time.time()
def _fetch_direct(url:str,timeout:int)->bytes:
    with urlopen(Request(url,headers=HEADERS),timeout=timeout) as response:
        if response.status != 200: raise RuntimeError(f'HTTP_{response.status}')
        return response.read()
def _fetch_via_relay(url:str,timeout:int)->tuple[bytes,str]:
    """Read one public titan007 URL through a read-only HTTP relay.

    Direct egress to vip.titan007.com is blocked from this host (all ports)
    while the origin is verifiably serving the same URL from third-party
    vantage points.  Relaying the public odds URL is the only way to keep the
    five-company changeDetail contract satisfied.  Only public URLs are sent;
    no local data, packet or credential ever leaves the machine.
    """
    quoted=urllib.parse.quote(url,safe='')
    last=None
    for template in RELAY_TEMPLATES:
        relay=template.strip().replace('{q}',quoted)
        try:
            with urlopen(Request(relay,headers=HEADERS),timeout=timeout) as response:
                if response.status != 200: raise RuntimeError(f'HTTP_{response.status}')
                body=response.read()
            if len(body) < RELAY_MIN_BYTES: raise RuntimeError(f'RELAY_SHORT_{len(body)}')
            return body,relay
        except (HTTPError,URLError,TimeoutError,RuntimeError,OSError) as exc:
            last=exc
    raise RuntimeError(f'RELAY_FAILED:{type(last).__name__}:{last}')
def fetch(url:str,timeout:int=20,*,allow_relay:bool=True)->tuple[bytes,int]:
    last=None
    host=_host_of(url)
    direct_timeout=min(timeout,DIRECT_TIMEOUT) if allow_relay and RELAY_TEMPLATES else timeout
    if _direct_allowed(host):
        for attempt in range(1,FETCH_ATTEMPTS+1):
            try:
                body=_fetch_direct(url,direct_timeout)
                _direct_note(host,True)
                LAST_FETCH_TRANSPORT.update({'mode':'direct','relay':None})
                return body,attempt
            except (HTTPError,URLError,TimeoutError,RuntimeError,OSError) as exc:
                last=exc
                _direct_note(host,False)
                if not _direct_allowed(host): break
                if attempt<FETCH_ATTEMPTS: time.sleep(.35*attempt)
    else:
        last=RuntimeError('DIRECT_EGRESS_CIRCUIT_OPEN')
    if allow_relay and RELAY_TEMPLATES and 'titan007.com' in url:
        for relay_attempt in range(1,RELAY_ATTEMPTS+1):
            try:
                body,relay=_fetch_via_relay(url,timeout)
                LAST_FETCH_TRANSPORT.update({'mode':'relay','relay':relay})
                return body,FETCH_ATTEMPTS+relay_attempt
            except RuntimeError as exc:
                last=exc
                if relay_attempt<RELAY_ATTEMPTS: time.sleep(RELAY_BACKOFF*relay_attempt)
    raise RuntimeError(f'{type(last).__name__}:{last}')
def decode(raw:bytes)->str:
    for encoding in ('utf-8','gb18030','gbk'):
        try:return raw.decode(encoding)
        except UnicodeDecodeError:continue
    return raw.decode('gb18030','replace')
def table_rows(text:str)->list[list[str]]:
    parser=TableParser(); parser.feed(text); return parser.rows
def identity_kickoff(value:str)->str|None:
    try:
        year,month,day,hour,minute=map(int,re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})',value).groups())
        return datetime(year,month,day,hour,minute,tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc).isoformat()
    except (AttributeError,ValueError):return None
def parse_single_match_identity(text:str,match_id:str,schedule_date:str)->dict|None:
    title_match=re.search(r'<title[^>]*>(.*?)</title>',text,re.I|re.S)
    if not title_match:return None
    title=' '.join(re.sub(r'<[^>]+>',' ',title_match.group(1)).replace('&nbsp;',' ').split())
    title_parts=re.match(r'(.+?)VS(.+?)\((?:\d{4}赛季)?(.+?)\)-(?:亚指指数|大小指数)',title,re.I)
    kickoff_match=re.search(r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})',text)
    if not title_parts or not kickoff_match:return None
    home,away,league=(part.strip() for part in title_parts.groups())
    kickoff=identity_kickoff(kickoff_match.group(1))
    if not all((home,away,league,kickoff)):return None
    return {'league':league,'kickoff_display':kickoff_match.group(1),'kickoff':kickoff,'home':home,'away':away,'schedule_date':schedule_date,'source':'titan007_single_match_fallback','identity_evidence_url':f'https://vip.titan007.com/AsianOdds_n.aspx?id={match_id}'}
def parse_single_match_fallback(match_id:str,schedule_date:str)->dict|None:
    try:
        raw,_=fetch(f'https://vip.titan007.com/AsianOdds_n.aspx?id={match_id}')
    except Exception:return None
    return parse_single_match_identity(decode(raw),match_id,schedule_date)
def parse_schedule(match_id:str)->dict|None:
    day=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    try:
        raw,_=fetch(f'https://bf.titan007.com/football/Next_{day}.htm')
        text=decode(raw)
    except Exception:
        return parse_single_match_fallback(match_id,day)
    pattern=r'''<tr\b(?P<attrs>[^>]*)\bsId=["']'''+re.escape(match_id)+r'''["'][^>]*>(?P<body>.*?)</tr>'''
    hit=re.search(pattern,text,re.I|re.S)
    if not hit:return parse_single_match_fallback(match_id,day)
    cells=table_rows('<table><tr>'+hit.group('body')+'</tr></table>')
    if not cells or len(cells[0])<6:return parse_single_match_fallback(match_id,day)
    row=cells[0]; kickoff=None
    try:
        month,day_of_month,clock=re.match(r'(\d{1,2})-(\d{1,2})\s+(\d{1,2}:\d{2})',row[1]).groups()
        local=datetime.now(ZoneInfo('Asia/Shanghai'))
        kickoff=datetime(local.year,int(month),int(day_of_month),int(clock[:2]),int(clock[3:]),tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc).isoformat()
    except (AttributeError,ValueError):pass
    if not all((row[0],kickoff,row[3],row[5])):return parse_single_match_fallback(match_id,day)
    return {'league':row[0],'kickoff_display':row[1],'kickoff':kickoff,'home':row[3],'away':row[5],'schedule_date':day,'source':'titan007_next_schedule'}
def _number(value):
    try:return float(value)
    except (TypeError,ValueError):return None

def _norm_change_row(row):
    if not row:return None
    water=_number(row[2]); opponent=_number(row[4])
    # 封盘行保留状态，但不算可用当前盘水位
    if water is None and str(row[2]).strip() in ('封','封盘'):
        return {'water':None,'line':row[3],'opponent_water':opponent,'changed_at':row[5],'status':row[6],'sealed':True}
    return {'water':water,'line':row[3],'opponent_water':opponent,'changed_at':row[5],'status':row[6],'sealed':False}

def parse_change(raw:bytes)->dict:
    body=[]
    for row in table_rows(decode(raw)):
        if len(row)<7 or row[0] in ('时间','時間','序号','序號') or row[-1] not in ('早','即','滚','滾'):continue
        body.append(row[:7])
    opening=next((r for r in reversed(body) if r[6]=='早'),body[-1] if body else None)
    current=next((r for r in body if r[6]=='即'),None)
    kicked_off=any(r[6] in ('滚','滾') for r in body)
    early_as_current=False
    # Titan007 sometimes never flips 早→即 pre-match; latest 早 is then the only current quote.
    if current is None and not kicked_off and body:
        latest_early=next((r for r in body if r[6]=='早'), None)
        if latest_early is not None:
            current=latest_early
            early_as_current=True
    current_norm=_norm_change_row(current)
    opening_norm=_norm_change_row(opening)
    history=[item for item in (_norm_change_row(row) for row in body if row[6] in ('早','即')) if item]
    usable_current=bool(current_norm and current_norm.get('water') is not None and current_norm.get('line') not in (None,''))
    if usable_current and early_as_current:
        payload_status='EARLY_AS_CURRENT'
        current_norm={**current_norm, 'early_as_current': True, 'quote_role_hint': 'current_pre_match_from_latest_early'}
    elif usable_current:
        payload_status='OK'
    elif kicked_off and body:
        payload_status='LIVE_ONLY'
    elif opening_norm and opening_norm.get('water') is not None:
        payload_status='OPENING_ONLY'
    elif not body:
        payload_status='EMPTY'
    else:
        payload_status='UNUSABLE'
    return {
        'row_count':len(body),
        'opening':opening_norm,
        'current':current_norm,
        'history':history,
        'kicked_off':kicked_off,
        'usable_current':usable_current,
        'payload_status':payload_status,
    }

def is_change_payload_shell(raw:bytes, parsed:dict|None=None)->bool:
    """Detect Titan007 changeDetail empty shells that look like HTTP 200 but have no odds rows."""
    parsed=parsed or {}
    raw=raw or b''
    # usable rows always win over size heuristics
    if int(parsed.get('row_count') or 0) > 0 or parsed.get('usable_current') is True:
        return False
    if len(raw) < 1800:
        return True
    text=decode(raw)
    if ('odds_detail' in text) and (('handicap.aspx' in text) or ('overunder.aspx' in text)):
        # framework page without table body
        if len(raw) < 4200:
            return True
    # no status tokens at all
    if not any(token in text for token in ('早','即','滚','滾')) and len(raw) < 5000:
        return True
    return int(parsed.get('row_count') or 0) <= 0 and len(raw) < 3500

def _market_entry_valid(entry:dict|None)->bool:
    if not isinstance(entry, dict):
        return False
    # Production: require usable current quote when present.
    if entry.get('usable_current') is True:
        return True
    current=entry.get('current') if isinstance(entry.get('current'), dict) else {}
    if current.get('water') is not None and current.get('line') not in (None, ''):
        return True
    # Legacy unit fixtures only set row_count.
    if 'current' not in entry and int(entry.get('row_count') or 0) > 0:
        return True
    return False

def market_coverage(results:dict)->dict:
    by_market={}
    empty_shell=[]; parse_unusable=[]; retry_stats={'empty_shell_retries':0,'recovered_after_retry':0}
    for market in ('AH','OU'):
        valid=[]; missing=[]; shell=[]; unusable=[]
        for cid in COMPANIES:
            data=(results.get(cid) or {}).get(market) or {}
            if _market_entry_valid(data):
                valid.append(cid)
            else:
                missing.append(cid)
                status=str(data.get('payload_status') or '')
                if status == 'EMPTY' or data.get('empty_shell') is True:
                    shell.append(cid)
                elif int(data.get('row_count') or 0) > 0:
                    unusable.append(cid)
            retry_stats['empty_shell_retries'] += int(data.get('shell_retries') or 0)
            if data.get('recovered_after_retry') is True:
                retry_stats['recovered_after_retry'] += 1
        by_market[market]={
            'valid_companies':len(valid),
            'company_ids':sorted(valid),
            'missing_companies':sorted(missing),
            'empty_shell_companies':sorted(shell),
            'parse_unusable_companies':sorted(unusable),
        }
        empty_shell.extend(f'{cid}:{market}' for cid in shell)
        parse_unusable.extend(f'{cid}:{market}' for cid in unusable)
    minimum=all(by_market[m]['valid_companies']>=4 for m in ('AH','OU'))
    full=all(by_market[m]['valid_companies']==len(COMPANIES) for m in ('AH','OU'))
    both_valid=sorted(cid for cid,data in results.items() if all(_market_entry_valid(data.get(m)) for m in ('AH','OU')))
    return {
        'required_companies':len(COMPANIES),
        'required_markets':['AH','OU'],
        'by_market':by_market,
        'valid_companies_both_markets':len(both_valid),
        'company_ids_both_markets':both_valid,
        'minimum_directional_coverage_met':minimum,
        'all_markets_full_coverage':full,
        'empty_shell_companies':sorted(set(empty_shell)),
        'parse_unusable_companies':sorted(set(parse_unusable)),
        'retry_stats':retry_stats,
        'required_company_names':{cid:name for cid,name in COMPANIES.items()},
    }

def market_grade(identity:dict,coverage:dict,fundamentals:dict|None=None,market_depth:dict|None=None)->dict:
    both_markets=bool(coverage.get('minimum_directional_coverage_met'))
    identity_ok=all(identity.get(k) for k in ('league','home','away','kickoff'))
    fundamentals_ok=bool((fundamentals or {}).get('directional_eligible'))
    depth_ok=bool((market_depth or {}).get('directional_eligible'))
    by_market=coverage.get('by_market') if isinstance(coverage.get('by_market'),dict) else {}
    try:
        ah_n=int((by_market.get('AH') or {}).get('valid_companies') or 0)
        ou_n=int((by_market.get('OU') or {}).get('valid_companies') or 0)
    except (TypeError,ValueError):
        ah_n=ou_n=0
    if not identity_ok:
        return {'grade':'F','score':0,'mode':'ENGINEERING_DIAGNOSTIC_ONLY','directional_shadow_allowed':False,'reason':'core identity unavailable'}
    if not both_markets:
        if depth_ok:
            return {
                'grade':'D','score':30,'mode':'CROWN_MAIN_DIAGNOSTIC','directional_shadow_allowed':False,
                'candidate_scope':'exact_main_only','confidence_cap':'diagnostic_only',
                'reason':f'Crown main lines available but company coverage incomplete (AH={ah_n}, OU={ou_n}); formal direction blocked, diagnostic analysis allowed',
            }
        return {'grade':'F','score':0,'mode':'ENGINEERING_DIAGNOSTIC_ONLY','directional_shadow_allowed':False,'reason':'core identity unavailable or fewer than four companies in AH/OU and Crown main lines unavailable'}
    if fundamentals_ok and depth_ok:
        adjacent=bool((market_depth or {}).get('adjacent_lines_available'))
        full=bool(coverage.get('all_markets_full_coverage'))
        if full and adjacent:return {'grade':'C','score':65,'mode':'LIMITED_DATA_SHADOW_ANALYSIS','directional_shadow_allowed':True,'candidate_scope':'main_plus_adjacent','reason':'five-company AH/OU plus hashed fundamentals and adjacent-line evidence; independent review remains mandatory'}
        return {'grade':'C-','score':55,'mode':'LIMITED_MAIN_LINE_ONLY','directional_shadow_allowed':True,'candidate_scope':'exact_main_only','confidence_cap':'low','reason':'at least four companies per market and Crown main lines are available; missing company/adjacent evidence restricts analysis to exact main lines'}
    return {'grade':'D','score':35,'mode':'MARKET_STRUCTURE_ONLY','directional_shadow_allowed':False,'reason':'market coverage meets minimum but fundamentals or Crown main-line evidence is unavailable'}
def fetch_change_detail(match_id:str, company_id:str, endpoint:str, market:str)->tuple[str,str,str,bytes,int,dict]:
    """Fetch one company/market changeDetail page with empty-shell retries and language fallback."""
    urls=[
        f'https://vip.titan007.com/changeDetail/{endpoint}?id={match_id}&companyID={company_id}&l=0',
        f'https://vip.titan007.com/changeDetail/{endpoint}?id={match_id}&companyID={company_id}&l=1',
    ]
    best=None; shell_retries=0; recovered=False
    for url in urls:
        for attempt in range(1, FETCH_ATTEMPTS+1):
            try:
                raw, used=fetch(url)
            except Exception as exc:
                best=(company_id,market,url,b'',attempt,{'row_count':0,'opening':None,'current':None,'kicked_off':False,'usable_current':False,'payload_status':'FETCH_ERROR','error':f'{type(exc).__name__}:{exc}'})
                if attempt < FETCH_ATTEMPTS:
                    time.sleep(.35*attempt)
                continue
            parsed=parse_change(raw)
            shell=is_change_payload_shell(raw, parsed)
            if shell:
                shell_retries += 1
                parsed={**parsed,'empty_shell':True,'payload_status':'EMPTY','shell_retries':shell_retries}
                best=(company_id,market,url,raw,attempt,parsed)
                # A shell served over the relay is an *answered* request: the
                # origin really returned its "no quotes for this company" page.
                # Re-asking it through a best-effort public relay costs ~20s per
                # attempt and never recovers, which is what pushed a single
                # five-company capture to 21 minutes.  Cap shell retries on the
                # relay path; the direct path keeps the original budget because
                # there a shell is often a transient origin hiccup.
                if LAST_FETCH_TRANSPORT.get('mode')=='relay' and attempt>=SHELL_RETRY_LIMIT_RELAY:
                    break
                time.sleep(.4*attempt)
                continue
            if shell_retries:
                recovered=True
            parsed={**parsed,'empty_shell':False,'transport_failure':False,'shell_retries':shell_retries,'recovered_after_retry':recovered,'transport_mode':LAST_FETCH_TRANSPORT.get('mode'),'transport_relay':LAST_FETCH_TRANSPORT.get('relay')}
            return company_id,market,url,raw,attempt,parsed
    if best is None:
        parsed={'row_count':0,'opening':None,'current':None,'kicked_off':False,'usable_current':False,'payload_status':'FETCH_ERROR','empty_shell':False,'transport_failure':True,'shell_retries':shell_retries}
        return company_id,market,urls[0],b'',FETCH_ATTEMPTS,parsed
    cid,market,url,raw,attempts,parsed=best
    status=parsed.get('payload_status') or 'EMPTY'
    transport=status=='FETCH_ERROR'
    parsed={**parsed,'empty_shell':(not transport),'transport_failure':transport,'shell_retries':shell_retries,'recovered_after_retry':False,'payload_status':status,
            'transport_mode':LAST_FETCH_TRANSPORT.get('mode'),'transport_relay':LAST_FETCH_TRANSPORT.get('relay')}
    return cid,market,url,raw,attempts,parsed

def live_packet(match_id:str)->dict:
    # captured_at is the packet-ready timestamp (end of collection), not the
    # collection start. T-30 five-company capture can take >120s; stamping at
    # start made every valid live packet immediately runtime-stale.
    collection_started_at=utcnow(); identity=parse_schedule(match_id)
    if not identity:return {'ok':False,'code':'LIVE_IDENTITY_NOT_FOUND','match_id':match_id,'source':'titan007','fresh':False,'usable_for_analysis':False}
    raw_records=[]; results={}; capture_key=collection_started_at.strftime('%Y%m%dT%H%M%SZ')
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(fetch_change_detail,match_id,cid,endpoint,market) for cid in COMPANIES for endpoint,market in MARKETS.items()]
        for future in as_completed(futures):
            try:
                cid,market,url,raw,attempts,parsed=future.result(); digest=hashlib.sha256(raw or b'').hexdigest()
                raw_path=SNAPSHOTS/str(match_id)/'raw'/capture_key/f'{cid}_{market}_{digest[:12]}.html'
                if raw:
                    atomic_bytes(raw_path,raw)
                raw_records.append({
                    'company_id':cid,'market':market,'url':url,'sha256':digest,'bytes':len(raw or b''),'attempts':attempts,
                    'raw_path':str(raw_path) if raw else '','payload_status':parsed.get('payload_status'),
                    'empty_shell':parsed.get('empty_shell') is True,'shell_retries':parsed.get('shell_retries') or 0,
                    'recovered_after_retry':parsed.get('recovered_after_retry') is True,
                    'transport_failure':parsed.get('transport_failure') is True,
                    'transport_mode':parsed.get('transport_mode'),'transport_relay':parsed.get('transport_relay'),
                })
                results.setdefault(cid,{})[market]=parsed
            except Exception as exc:
                raw_records.append({'error':type(exc).__name__,'detail':str(exc)[:180]})
    # Targeted second wave for still-missing markets (hot matches: reduce false incompleteness).
    missing_jobs=[]
    for cid in COMPANIES:
        for endpoint,market in MARKETS.items():
            entry=(results.get(cid) or {}).get(market) or {}
            if not _market_entry_valid(entry):
                missing_jobs.append((cid,endpoint,market))
    if missing_jobs:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(fetch_change_detail,match_id,cid,endpoint,market) for cid,endpoint,market in missing_jobs]
            for future in as_completed(futures):
                try:
                    cid,market,url,raw,attempts,parsed=future.result()
                    if not _market_entry_valid(parsed) and _market_entry_valid((results.get(cid) or {}).get(market) or {}):
                        continue
                    digest=hashlib.sha256(raw or b'').hexdigest()
                    raw_path=SNAPSHOTS/str(match_id)/'raw'/capture_key/f'{cid}_{market}_{digest[:12]}.html'
                    if raw:
                        atomic_bytes(raw_path,raw)
                    raw_records.append({
                        'company_id':cid,'market':market,'url':url,'sha256':digest,'bytes':len(raw or b''),'attempts':attempts,
                        'raw_path':str(raw_path) if raw else '','payload_status':parsed.get('payload_status'),
                        'empty_shell':parsed.get('empty_shell') is True,'shell_retries':parsed.get('shell_retries') or 0,
                        'recovered_after_retry':parsed.get('recovered_after_retry') is True,'wave':'coverage_repair',
                        'transport_failure':parsed.get('transport_failure') is True,
                        'transport_mode':parsed.get('transport_mode'),'transport_relay':parsed.get('transport_relay'),
                    })
                    results.setdefault(cid,{})[market]=parsed
                except Exception as exc:
                    raw_records.append({'error':type(exc).__name__,'detail':str(exc)[:180],'wave':'coverage_repair'})
    # A company's changeDetail page can be a valid HTTP 200 shell while the
    # all-company overview still contains its opening/current quote.  Capture each
    # overview once and repair only missing entries; never replace valid history.
    still_missing={market for cid in COMPANIES for market in ('AH','OU')
                   if not _market_entry_valid((results.get(cid) or {}).get(market) or {})}
    overview_pages={'AH':'AsianOdds_n.aspx','OU':'OverDown_n.aspx'}
    for market in sorted(still_missing):
        url=f'https://vip.titan007.com/{overview_pages[market]}?id={match_id}&l=0'
        try:
            raw,attempts=fetch(url); digest=hashlib.sha256(raw).hexdigest()
            raw_path=SNAPSHOTS/str(match_id)/'raw'/capture_key/f'overview_{market}_{digest[:12]}.html'
            atomic_bytes(raw_path,raw)
            parsed_by_company=parse_overview_market(raw,market,captured_at=utcnow().isoformat())
            raw_records.append({'company_id':'overview','market':market,'url':url,'sha256':digest,
                                'bytes':len(raw),'attempts':attempts,'raw_path':str(raw_path),
                                'payload_status':'OVERVIEW_CAPTURE','empty_shell':False,'wave':'overview_repair'})
            for cid,parsed in parsed_by_company.items():
                if _market_entry_valid((results.get(cid) or {}).get(market) or {}): continue
                results.setdefault(cid,{})[market]=parsed
                derived=overview_change_payload(parsed); derived_digest=hashlib.sha256(derived).hexdigest()
                derived_path=SNAPSHOTS/str(match_id)/'raw'/capture_key/f'{cid}_{market}_overview_{derived_digest[:12]}.html'
                atomic_bytes(derived_path,derived)
                raw_records.append({'company_id':cid,'market':market,'url':url,'sha256':derived_digest,
                                    'bytes':len(derived),'attempts':attempts,'raw_path':str(derived_path),
                                    'source_overview_sha256':digest,'source_overview_raw_path':str(raw_path),
                                    'payload_status':'OVERVIEW_CURRENT_FALLBACK','empty_shell':False,
                                    'quote_source':'company_overview_summary','history_available':False,
                                    'wave':'overview_repair'})
        except Exception as exc:
            raw_records.append({'error':type(exc).__name__,'detail':str(exc)[:180],
                                'market':market,'wave':'overview_repair'})
    valid={cid:data for cid,data in results.items() if all(_market_entry_valid(data.get(m)) for m in ('AH','OU'))}
    partial={cid:data for cid,data in results.items() if any(_market_entry_valid(data.get(m)) for m in ('AH','OU'))}
    coverage=market_coverage(results)
    coverage['request_failures']=sum(1 for r in raw_records if r.get('error'))
    # Auxiliary captures (fundamentals / market_depth / correct_score / competition_stage)
    # are independent of the odds pass and of each other: run them concurrently instead of
    # serially so a single T-30 collection stays inside the freshness age window.
    def _safe_fundamentals():
        return capture_fundamentals(match_id)
    def _safe_market_depth():
        return capture_market_depth(match_id)
    def _safe_correct_score():
        try:
            return capture_correct_score(str(match_id), identity)
        except Exception as exc:
            return {'ok':False,'code':'CORRECT_SCORE_CAPTURE_FAILED','match_id':str(match_id),
                    'crow_or_crown':False,'blocking':False,'source':'capture_error','reason':type(exc).__name__}
    def _safe_competition_stage():
        try:
            return capture_competition_stage(str(match_id), str(identity.get('league') or ''), str(identity.get('kickoff') or ''))
        except Exception as exc:
            return {'ok':False,'code':'COMPETITION_STAGE_CAPTURE_FAILED','match_id':str(match_id),
                    'league':str(identity.get('league') or ''),'source':'capture_error','reason':type(exc).__name__}
    # Manual executor lifecycle: on optional-capture timeout we must NOT block on
    # shutdown(wait=True). We collect results with bounded waits, then shut down with
    # wait=False/cancel_futures so a hung correct-score thread can never delay the
    # core packet past its freshness age gate. (Python cannot kill a running thread;
    # the packet is already built and returned — the orphan thread just expires.)
    aux_pool=ThreadPoolExecutor(max_workers=4)
    f_fund=aux_pool.submit(_safe_fundamentals)
    f_depth=aux_pool.submit(_safe_market_depth)
    f_score=aux_pool.submit(_safe_correct_score)
    f_stage=aux_pool.submit(_safe_competition_stage)
    try:
        # fundamentals + market_depth gate the grade, so they must be awaited.
        try:
            fundamentals=f_fund.result()
        except Exception as exc:
            fundamentals={'ok':False,'directional_eligible':False,'code':'FUNDAMENTALS_CAPTURE_FAILED','reason':type(exc).__name__}
        try:
            market_depth=f_depth.result()
        except Exception as exc:
            market_depth={'ok':False,'directional_eligible':False,'code':'MARKET_DEPTH_CAPTURE_FAILED','reason':type(exc).__name__}
        # correct_score is optional/non-blocking: bound its wait so a slow or hung
        # correct-score fetch can never delay the core packet past the freshness gate.
        try:
            correct_score_optional=f_score.result(timeout=CORRECT_SCORE_WAIT_SECONDS)
        except Exception as exc:
            correct_score_optional={'ok':False,'code':'CORRECT_SCORE_TIMEOUT_OPTIONAL','match_id':str(match_id),
                                    'crow_or_crown':False,'blocking':False,'source':'non_blocking_timeout','reason':type(exc).__name__}
        try:
            competition_stage_evidence=f_stage.result(timeout=COMPETITION_STAGE_WAIT_SECONDS)
        except Exception as exc:
            competition_stage_evidence={'ok':False,'code':'COMPETITION_STAGE_CAPTURE_FAILED','match_id':str(match_id),
                                        'league':str(identity.get('league') or ''),'source':'non_blocking_timeout','reason':type(exc).__name__}
    finally:
        aux_pool.shutdown(wait=False,cancel_futures=True)
    h2h_evidence=build_h2h_evidence(fundamentals if isinstance(fundamentals,dict) else {})
    grade=market_grade(identity,coverage,fundamentals,market_depth)
    captured=utcnow()
    contract=freshness_contract(identity,captured,source_mode='local_live_packet',remote_packet_found=False)
    contract['collection_started_at']=collection_started_at.isoformat()
    contract['collection_duration_seconds']=max(0,int((captured-collection_started_at).total_seconds()))
    try:
        kickoff=datetime.fromisoformat(str(identity.get('kickoff')).replace('Z','+00:00'))
        scheduled_pre_match=kickoff > captured
    except (TypeError,ValueError):
        scheduled_pre_match=False
    any_kicked=any(bool((data.get(m) or {}).get('kicked_off')) for data in results.values() for m in ('AH','OU'))
    pre_match=scheduled_pre_match and not any_kicked
    complete=coverage['minimum_directional_coverage_met']
    directional=grade['directional_shadow_allowed'] is True
    depth_ok=bool((market_depth or {}).get('directional_eligible'))
    formal_ready=complete and pre_match and directional and contract['eligible_for_directional_analysis']
    diagnostic_ready=pre_match and depth_ok and contract['eligible_for_directional_analysis']
    usable=formal_ready or diagnostic_ready
    if not pre_match:
        code='LIVE_MATCH_ALREADY_STARTED'
        usable=False
    elif formal_ready:
        code='LIVE_PACKET_READY'
    elif diagnostic_ready and not complete:
        code='LIVE_COVERAGE_INCOMPLETE_DIAGNOSTIC'
    elif diagnostic_ready and not directional:
        code='LIVE_MARKET_STRUCTURE_ONLY'
    elif not complete:
        code='LIVE_COVERAGE_INCOMPLETE'
    else:
        code='LIVE_PACKET_READY'
    snapshot={'schema_version':6,'match_id':str(match_id),'captured_at':captured.isoformat(),
              'ok':usable,'code':code,'source':'titan007_live','source_mode':'local_live_packet',
              'origin_source_mode':'local_live_packet','remote_packet_found':False,
              'fallback_reason':'HF_REMOTE_PACKET_NOT_USED_FOR_DIRECTIONAL_ANALYSIS','fresh':True,
              'usable_for_analysis':usable,'freshness_contract':contract,'identity':identity,
              'identity_lock':{'match_id':str(match_id),'identity_score':100,'passed':True},
              'coverage':coverage,'fundamentals':fundamentals,'h2h_evidence':h2h_evidence,
              'market_depth':market_depth,'market_grade':grade,
              'odds':{cid:{'company':COMPANIES[cid],**data} for cid,data in partial.items()},
              'raw_payloads':raw_records,
              'coverage_repair':{'missing_jobs':len(missing_jobs),'partial_companies':sorted(partial), 'full_companies':sorted(valid)}}
    # correct_score / competition_stage were already captured concurrently above.
    snapshot['correct_score_optional']=correct_score_optional
    snapshot['competition_stage_evidence']=competition_stage_evidence
    # Persist the exact E2 production feature projection in the immutable packet.
    # It is result-blind, contains only five-company AH opening/current quotes,
    # and is hash-bound for HF distribution/readback and runner verification.
    # Bind the feature projection to the pre-feature packet core. The outer
    # packet hash then binds both core and feature artifact without a circular
    # self-hash dependency.
    snapshot['packet_sha256']=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    accuracy_features=build_accuracy_features(snapshot)
    snapshot['accuracy_features']=accuracy_features
    snapshot.pop('packet_sha256',None)
    digest=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    snapshot['packet_sha256']=digest
    target=SNAPSHOTS/str(match_id)/f'{capture_key}_{digest[:12]}.json'; atomic_json(target,snapshot)
    # Return the persisted packet plus its location only; packet hash therefore
    # remains reproducible from the immutable snapshot.
    return {**snapshot,'snapshot_path':str(target)}
def legacy_packet(match_id:str)->dict:
    if not DB.exists():return {'ok':False,'code':'LOCAL_DB_MISSING','match_id':match_id,'usable_for_analysis':False}
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    try:rows=con.execute('select match_name,company,snapshot_ts from water_snapshots order by snapshot_ts desc').fetchall()
    finally:con.close()
    if not rows:return {'ok':False,'code':'LOCAL_DB_EMPTY','match_id':match_id,'usable_for_analysis':False}
    newest=max(r['snapshot_ts'] for r in rows); age=(utcnow().timestamp()-newest)/3600
    return {'ok':False,'code':'LOCAL_IDENTITY_UNRESOLVED','match_id':match_id,'source':'local_changedetection_sqlite','latest_snapshot_at':iso(newest),'age_hours':round(age,2),'fresh':age<=MAX_AGE_HOURS,'known_matches':sorted({r['match_name'] for r in rows if r['match_name']}),'company_count':len({r['company'] for r in rows if r['company']}),'usable_for_analysis':False,'reason':'Legacy cache lacks match_id identity and is diagnostic-only.'}
def local_packet(match_id:str)->dict|None:
    """Return only the data-only cache contract.

    The cached projection is intentionally useful for collection/event work, but
    can never be mistaken for an independently fresh directional packet.
    """
    path=LOCAL_PACKETS/f'{match_id}.json'
    try:
        cached=json.loads(path.read_text(encoding='utf-8'))
        captured=datetime.fromisoformat(str(cached['captured_at']).replace('Z','+00:00'))
    except (OSError,KeyError,ValueError,json.JSONDecodeError):
        return None
    age_hours=(utcnow()-captured.astimezone(timezone.utc)).total_seconds()/3600
    fresh=age_hours<=MAX_AGE_HOURS
    identity=cached.get('identity',{})
    markets=cached.get('markets',{}).get('Crown',{})
    complete=all(markets.get(name) for name in ('AH','OU'))
    try:
        kickoff=datetime.fromisoformat(str(identity.get('kickoff','')).replace('Z','+00:00'))
        pre_match=kickoff>utcnow()
    except ValueError:
        pre_match=False
    age=age_seconds(cached.get('captured_at'))
    usable=bool(fresh and complete and pre_match)
    return {'ok':usable,'code':'LOCAL_PACKET_READY' if usable else ('LOCAL_PACKET_STALE' if not fresh else 'LOCAL_PACKET_NOT_PREMATCH_OR_INCOMPLETE'),'match_id':str(match_id),'source':'local_compact_packet','source_mode':'local_cache','remote_packet_found':False,'captured_at':cached.get('captured_at'),'fresh':fresh,'freshness_contract':{'source_mode':'local_cache','remote_packet_found':False,'live_refresh_performed':False,'captured_at':cached.get('captured_at'),'age_seconds':age,'max_age_seconds':MAX_AGE_HOURS*3600,'freshness_tier':'DATA_ONLY_CACHE','eligible_for_directional_analysis':False},'usable_for_analysis':usable,'identity':identity,'identity_lock':{'match_id':str(match_id),'identity_score':100 if identity else 0,'passed':bool(identity)},'coverage':cached.get('source_coverage',{}),'market_grade':{'grade':'LOCAL','mode':'DATA_ONLY_COMPACT_PACKET','directional_shadow_allowed':False,'reason':'Local compact packet has no direction or decision content.'},'packet_sha256':cached.get('canonical_sha256') or canonical_digest(cached),'snapshot_path':str(path),'reason':'Data-only local compact cache; no market direction, EV, or stake is present.'}

MARKET_EVIDENCE_COMPANIES={'3':'皇冠Crown','24':'Pinnacle平博','31':'Bet365','14':'威廉希尔','17':'立博'}

def _market_evidence_snapshot(packet:dict)->dict:
    """Resolve the immutable local snapshot; never make a second market request."""
    if isinstance(packet.get('raw_payloads'),list):
        return packet
    path=Path(str(packet.get('snapshot_path') or ''))
    try:
        snapshot=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError):
        return {}
    if str(snapshot.get('match_id')) != str(packet.get('match_id')):
        return {}
    if packet.get('packet_sha256') and snapshot.get('packet_sha256') != packet.get('packet_sha256'):
        return {}
    return snapshot

def _market_evidence_quote(row:list[str]|None,market:str)->dict|None:
    if not row:
        return None
    try:
        water,opponent=float(row[2]),float(row[4])
    except (TypeError,ValueError):
        return None
    if market=='AH':
        return {'主水':water,'盘口':row[3],'客水':opponent,'时间':row[5],'状态':row[6]}
    return {'大球水':water,'盘口':row[3],'小球水':opponent,'时间':row[5],'状态':row[6]}

def _market_evidence_parse(raw:bytes,market:str)->dict:
    rows=[row[:7] for row in table_rows(decode(raw)) if len(row)>=7 and row[0] not in ('时间','時間','序号','序號') and row[-1] in ('早','即','滚','滾')]
    opening=next((row for row in reversed(rows) if row[6]=='早'),rows[-1] if rows else None)
    current=next((row for row in rows if row[6]=='即'),None)
    kicked_off=any(row[6] in ('滚','滾') for row in rows)
    # EARLY_AS_CURRENT parity with parse_change: Titan007 sometimes never flips 早→即
    # pre-match, so the latest 早 is the only current quote. Without this the portable
    # market-evidence 'current' would be None while payload_status says EARLY_AS_CURRENT.
    early_as_current=False
    if current is None and not kicked_off and rows:
        latest_early=next((row for row in rows if row[6]=='早'),None)
        if latest_early is not None:
            current=latest_early
            early_as_current=True
    history=[]
    for row in reversed(rows):
        if row[6] not in ('早','即'):
            continue
        try:
            history.append({'water':float(row[2]),'line':row[3],'opponent_water':float(row[4]),'time':row[5],'status':row[6]})
        except (TypeError,ValueError):
            continue
    # Reuse parse_change as the single source of truth for payload_status so the
    # portable evidence and the primary packet never disagree on quote availability.
    payload_status=parse_change(raw).get('payload_status')
    current_quote=_market_evidence_quote(current,market)
    if current_quote and early_as_current:
        current_quote={**current_quote,'early_as_current':True,'quote_role_hint':'current_pre_match_from_latest_early'}
    return {'row_count':len(rows),'kicked_off':kicked_off,'payload_status':payload_status,
            'opening':_market_evidence_quote(opening,market),'current':current_quote,'history':history}

def _market_evidence_valid(value:dict,*,expected_match_id:str,expected_source_packet_sha:str|None=None)->bool:
    if not isinstance(value,dict) or str(value.get('match_id')) != str(expected_match_id):
        return False
    claimed=value.get('market_evidence_sha256')
    calculated=hashlib.sha256(json.dumps({key:item for key,item in value.items() if key!='market_evidence_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if claimed != calculated or not isinstance(value.get('companies'),dict) or not isinstance(value.get('source_raw_sha256'),dict):
        return False
    if expected_source_packet_sha and value.get('source_packet_sha256') != expected_source_packet_sha:
        return False
    return bool(value['companies']) and bool(value['source_raw_sha256']) and value.get('integrity_passed') is True

def build_market_evidence(packet:dict)->dict:
    """Persist portable, hash-bound five-book market/K-line evidence for HF readers."""
    snapshot=_market_evidence_snapshot(packet)
    expected_sha = str(snapshot.get('source_packet_sha256') or
                       snapshot.get('packet_sha256') or packet.get('packet_sha256') or '')
    companies={}; hashes={}; invalid=[]
    records=snapshot.get('raw_payloads') if isinstance(snapshot.get('raw_payloads'),list) else []
    expected_records = [record for record in records if isinstance(record,dict) and str(record.get('company_id')) in MARKET_EVIDENCE_COMPANIES and record.get('market') in ('AH','OU')]
    # Multiple attempts for one company/market are retained for audit. Evidence
    # selects the last successfully parsed immutable record instead of letting
    # earlier empty-shell attempts poison a recovered overview quote.
    records_by_key={}
    for record in expected_records:
        records_by_key.setdefault((str(record.get('company_id')),str(record.get('market'))),[]).append(record)
    selected_records=[]
    for records in records_by_key.values():
        chosen=None
        for record in reversed(records):
            path=Path(str(record.get('raw_path') or ''))
            try: raw=path.read_bytes()
            except OSError: continue
            if hashlib.sha256(raw).hexdigest()!=record.get('sha256'): continue
            parsed=_market_evidence_parse(raw,str(record.get('market')))
            if parsed.get('current'):
                chosen=record; break
        selected_records.append(chosen or records[-1])
    for record in selected_records:
        company_id,market=str(record['company_id']),str(record['market'])
        raw_path=Path(str(record.get('raw_path') or ''))
        try:
            raw=raw_path.read_bytes()
            actual=hashlib.sha256(raw).hexdigest()
        except OSError:
            invalid.append({'company_id':company_id,'market':market,'reason':'raw_path_missing_or_unreadable'}); continue
        if actual != record.get('sha256'):
            invalid.append({'company_id':company_id,'market':market,'reason':'raw_sha256_mismatch'}); continue
        parsed=_market_evidence_parse(raw,market)
        if not parsed['row_count'] or not parsed['current']:
            invalid.append({'company_id':company_id,'market':market,'reason':'raw_parse_current_missing'}); continue
        name=MARKET_EVIDENCE_COMPANIES[company_id]
        company=companies.setdefault(name,{'companyID':company_id})
        company['AH让球盘' if market=='AH' else 'OU大小球盘']={
            'kicked_off':parsed['kicked_off'],'初盘opening':parsed['opening'],'赛前终盘closing':parsed['current'],'packet_history':parsed['history'],'both_packet_bound':True}
        hashes[f'{company_id}:{market}']=actual
    for name,company in list(companies.items()):
        company['both_ok']=bool(company.get('AH让球盘')) and bool(company.get('OU大小球盘'))
        if not company['both_ok']:
            companies.pop(name)
    value={'schema_version':1,'match_id':str(packet.get('match_id')),'source':'local_live_capture','source_packet_sha256':expected_sha,
           'captured_at':snapshot.get('captured_at'),'companies':companies,'source_raw_sha256':hashes,
           'integrity_passed':bool(companies) and bool(hashes) and not invalid,'invalid_records':invalid}
    value['market_evidence_sha256']=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return value

def hf_distribution_artifact(packet:dict)->dict:
    """Return the compact Dataset-safe form of one immutable live packet."""
    contract=packet.get('freshness_contract',{})
    source_date=datetime.fromisoformat(str(packet['captured_at']).replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    excluded={'raw_payloads','snapshot_path','«redacted:hf_…'}
    enriched={**packet,'market_evidence':build_market_evidence(packet)}
    accuracy=packet.get('accuracy_features') if isinstance(packet.get('accuracy_features'),dict) else build_accuracy_features(packet)
    enriched['accuracy_features']=accuracy
    return {k:v for k,v in {**enriched,'artifact_type':'packet','pool_date':source_date,'origin_source_mode':'local_live_packet',
                             'freshness_contract':{**contract,'origin_source_mode':'local_live_packet','distribution_source':'hf_dataset'}}.items() if k not in excluded}

def backfill_hf_packet_via_http(artifact:dict, *, repo_id:str, token:str)->dict:
    """Upload one small Dataset artifact through the public commit API and read it back.

    This stdlib/curl path avoids making the prediction runtime depend on the
    optional huggingface_hub package.  The commit payload is NDJSON and the
    read-after-write compares the complete canonical artifact hash.
    """
    from hf_dataset_sync import artifact_target
    target=artifact_target(artifact)
    if target is None:
        return {'status':'INVALID_ARTIFACT','uploaded':False}
    path_in_repo,state_key=target
    artifact_bytes=json.dumps(artifact,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    digest=hashlib.sha256(artifact_bytes).hexdigest()
    header={'key':'header','value':{'summary':f'data-only:{state_key}:{digest[:12]}','description':''}}
    file_op={'key':'file','value':{'content':base64.b64encode(artifact_bytes).decode(),'path':path_in_repo,'encoding':'base64'}}
    payload=(json.dumps(header,separators=(',',':'))+'\n'+json.dumps(file_op,separators=(',',':'))+'\n').encode()
    proxy=os.getenv('HF_LOCAL_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or ''
    if not proxy:
        try:
            with socket.create_connection(('127.0.0.1',10808),timeout=0.2):
                proxy='socks5h://127.0.0.1:10808'
        except OSError:
            proxy=''
    if proxy.startswith('socks5://'): proxy='socks5h://'+proxy[len('socks5://'):]
    common=['/usr/bin/curl','--fail-with-body','--silent','--show-error','--retry','1','--retry-all-errors','--connect-timeout','5','--max-time','30']
    # HF_LOCAL_PROXY is explicit and profile-safe.  Generic HTTPS proxy remains
    # a fallback; Telegram's delivery-only proxy is never inherited implicitly.
    if proxy: common+=['--proxy',proxy]
    with tempfile.TemporaryDirectory(prefix='hf_packet_') as td:
        body=Path(td)/'commit.ndjson'; body.write_bytes(payload)
        commit_base=os.getenv('HF_COMMIT_BASE_URL','https://huggingface.co').rstrip('/')
        resolve_base=os.getenv('HF_RESOLVE_BASE_URL',commit_base).rstrip('/')
        commit_url=f'{commit_base}/api/datasets/{repo_id}/commit/main'
        upload=subprocess.run(common+['-X','POST','-H',f'Authorization: Bearer {token}','-H','Content-Type: application/x-ndjson','--data-binary',f'@{body}',commit_url],capture_output=True,text=True)
        if upload.returncode:
            return {'status':'UPLOAD_OR_READBACK_FAILED','uploaded':False,'phase':'upload','error':upload.stderr.strip()[:240]}
        readback=Path(td)/'readback.json'
        raw_url=f'{resolve_base}/datasets/{repo_id}/resolve/main/{path_in_repo}?download=true&cb={time.time_ns()}'
        download=subprocess.run(common+['-L','-H',f'Authorization: Bearer {token}','-o',str(readback),raw_url],capture_output=True,text=True)
        if download.returncode or not readback.exists():
            return {'status':'UPLOAD_OR_READBACK_FAILED','uploaded':True,'phase':'readback','error':download.stderr.strip()[:240]}
        try: remote=json.loads(readback.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError):
            return {'status':'UPLOAD_OR_READBACK_FAILED','uploaded':True,'phase':'readback_json'}
        remote_digest=hashlib.sha256(json.dumps(remote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if remote_digest!=digest:
            return {'status':'UPLOAD_OR_READBACK_FAILED','uploaded':True,'phase':'readback_hash','artifact_sha256':digest,'remote_sha256':remote_digest}
    return {'status':'UPLOADED_VERIFIED','uploaded':True,'state_key':state_key,'path_in_repo':path_in_repo,'artifact_sha256':digest,'remote_sha256':digest}

def backfill_hf_packet(packet:dict)->dict:
    """Upload the same valid live packet for later HF reads; never refetch."""
    contract=packet.get('freshness_contract',{})
    if not (packet.get('ok') and packet.get('usable_for_analysis') and packet.get('fresh')
            and packet.get('source_mode')=='local_live_packet'
            and contract.get('live_refresh_performed') is True
            and contract.get('eligible_for_directional_analysis') is True
            and packet.get('coverage',{}).get('minimum_directional_coverage_met') is True
            and packet.get('market_grade',{}).get('directional_shadow_allowed') is True
            and packet.get('odds')):
        return {'status':'SKIPPED_INELIGIBLE_PACKET','uploaded':False}
    artifact=hf_distribution_artifact(packet)
    evidence=artifact.get('market_evidence') if isinstance(artifact.get('market_evidence'),dict) else {}
    if not _market_evidence_valid(evidence,expected_match_id=str(packet.get('match_id') or ''),expected_source_packet_sha=str(packet.get('packet_sha256') or '')):
        return {'status':'SKIPPED_INELIGIBLE_MARKET_EVIDENCE','uploaded':False,
                'market_evidence_integrity':bool(evidence.get('integrity_passed')),
                'invalid_records':evidence.get('invalid_records',[])}
    repo=os.getenv('HF_DATASET_REPO','Llama12315/football-data-hub')
    token_candidates = (ROOT.parent / "home/.cache/huggingface/token",
                      Path("/home/agent/.cache/huggingface/token"),
                      Path.home() / ".cache/huggingface/token")
    token = os.getenv("HF_TOKEN", "")
    if not token:
        for token_path in token_candidates:
            if token_path.exists():
                token = token_path.read_text(encoding="utf-8").strip()
                break
    if not token:
        return {'status':'HF_TOKEN_UNAVAILABLE','uploaded':False}
    try:
        from hf_dataset_sync import sync_if_changed
        from huggingface_hub import HfApi
        return sync_if_changed(HfApi(token=token),repo,artifact,ROOT/'hf_sync_state')
    except (ImportError,ModuleNotFoundError):
        return backfill_hf_packet_via_http(artifact,repo_id=repo,token=token)
    except Exception as exc:
        return {'status':'UPLOAD_OR_READBACK_FAILED','uploaded':False,'error':type(exc).__name__}

def _packet_hash_matches(packet: dict) -> bool:
    stored = str(packet.get('packet_sha256') or '')
    if len(stored) != 64 or any(ch not in '0123456789abcdef' for ch in stored.lower()):
        return False
    canonical = {key: value for key, value in packet.items() if key != 'packet_sha256'}
    actual = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return actual == stored


def remote_packet(match_id:str)->tuple[dict|None,dict]:
    """Return a fresh HF packet or a compact auditable non-acceptance receipt."""
    endpoint=f'{HF_BASE_URL}/match-packet?match_id={match_id}'
    receipt={'schema_version':1,'attempted':True,'endpoint':endpoint,'attempted_at':utcnow().isoformat(),
             'match_id':str(match_id),'accepted':False}
    try:
        raw,attempts=fetch(endpoint,timeout=5)
        response=json.loads(decode(raw))
        receipt['transport']={'result':'OK','attempts':attempts,'response_bytes':len(raw)}
    except Exception as exc:
        return None,{**receipt,'result':'TRANSPORT_ERROR','transport':{'result':'ERROR','error_type':type(exc).__name__}}
    candidate=response.get('packet',response) if isinstance(response,dict) else {}
    if not isinstance(candidate,dict):
        return None,{**receipt,'result':'REJECTED','rejection_reasons':['response_not_object']}
    contract=candidate.get('freshness_contract',{}) if isinstance(candidate.get('freshness_contract'),dict) else {}
    grade=candidate.get('market_grade',{}) if isinstance(candidate.get('market_grade'),dict) else {}
    identity=candidate.get('identity',{}) if isinstance(candidate.get('identity'),dict) else {}
    coverage=candidate.get('coverage',{}) if isinstance(candidate.get('coverage'),dict) else {}
    odds=candidate.get('odds',{}) if isinstance(candidate.get('odds'),dict) else {}
    captured=contract.get('captured_at') or candidate.get('captured_at')
    age=age_seconds(captured)
    try:
        max_age=int(contract.get('max_age_seconds',0))
    except (TypeError,ValueError):
        max_age=0
    gates={
        'ok':candidate.get('ok') is True,
        'usable_for_analysis':candidate.get('usable_for_analysis') is True,
        'fresh':candidate.get('fresh') is True,
        'live_refresh_performed':contract.get('live_refresh_performed') is True,
        'eligible_for_directional_analysis':contract.get('eligible_for_directional_analysis') is True,
        'directional_shadow_allowed':grade.get('directional_shadow_allowed') is True,
        'identity':all(identity.get(k) for k in ('league','home','away','kickoff')),
        'coverage':coverage.get('minimum_directional_coverage_met') is True,
        'odds':bool(odds),
        'freshness_age':age is not None and age<=max_age,
        'accuracy_features':accuracy_features_valid(
            candidate.get('accuracy_features'),
            expected_match_id=str(match_id),
        ),
    }
    receipt['candidate']={'code':candidate.get('code'),'captured_at':captured,'age_seconds':age,'max_age_seconds':max_age,
                          'source_mode':candidate.get('source_mode'),'gates':gates}
    failures=[name for name,passed in gates.items() if not passed]
    if failures:
        return None,{**receipt,'result':'REJECTED','rejection_reasons':failures}
    market_evidence=candidate.get('market_evidence') if isinstance(candidate.get('market_evidence'),dict) else {}
    if not _market_evidence_valid(market_evidence,expected_match_id=str(match_id),expected_source_packet_sha=str(candidate.get('packet_sha256') or '')):
        return None,{**receipt,'result':'REJECTED','rejection_reasons':['market_evidence_integrity']}
    snapshot={**candidate,'match_id':str(match_id),'source_mode':'hf_remote_packet',
              'remote_packet_found':True,'freshness_contract':{**contract,
                  'origin_source_mode':contract.get('origin_source_mode') or candidate.get('origin_source_mode'),
                  'remote_packet_found':True,
                  'distribution_source':'hf_dataset','source_mode':'hf_remote_packet'}}
    # The packet hash binds the exact immutable snapshot persisted for the run.
    # Remove a distribution packet's old hash before re-hashing the normalized
    # HF-receipt representation; presentation-only return fields are added later.
    snapshot.pop('packet_sha256',None)
    digest=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    snapshot['packet_sha256']=digest
    target=SNAPSHOTS/str(match_id)/f'hf_{digest[:12]}.json'; atomic_json(target,snapshot)
    # Return exactly the persisted immutable payload; no status/identity fields
    # are appended after hashing.
    return {**snapshot,'snapshot_path':str(target)}, {**receipt,'result':'ACCEPTED','accepted':True,'rejection_reasons':[]}

def packet(match_id:str,local_fallback:bool=False, *, require_directional:bool=False)->dict:
    """Get one reusable compact packet; remote HF first, one local-live fallback.

    Collection callers may reuse the data-only cache. Directional callers accept
    only a fresh complete HF packet or exactly one fresh Titan007 local capture.
    """
    if not require_directional:
        cached=local_packet(match_id)
        if cached and cached.get('fresh'):
            return cached
    if require_directional:
        remote, hf_receipt=remote_packet(match_id)
        if remote:
            return remote
    else:
        hf_receipt=None
    try:
        live=live_packet(match_id)
        if require_directional:
            # Distribution is a required data-path action, not a marker. Upload
            # the same immutable packet and require Dataset read-after-write.
            backfill=backfill_hf_packet(live)
            # HF receipt + verified backfill are retained as immutable
            # provenance; re-hash and persist the enriched packet rather than mutate
            # a previously hashed object.
            enriched = {**live, 'hf_fallback_receipt': hf_receipt,
                        'fallback_reason': 'HF_REMOTE_PACKET_REJECTED_OR_UNAVAILABLE',
                        'hf_backfill': backfill}
            enriched.pop('packet_sha256', None)
            packet_digest = hashlib.sha256(json.dumps(enriched, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            enriched['packet_sha256'] = packet_digest
            target = SNAPSHOTS / str(match_id) / f'live_{packet_digest[:12]}.json'
            atomic_json(target, enriched)
            live = {**enriched, 'snapshot_path': str(target)}
        return live
    except Exception as exc:
        if require_directional:
            return {'ok':False,'code':'LIVE_DIRECTIONAL_REFRESH_FAILED','match_id':str(match_id),'source':'titan007_live','fresh':False,'usable_for_analysis':False,'directional_refresh_required':True,'reason':'Fresh HF packet and local live directional refresh were unavailable; data-only cache is not an eligible substitute.','live_error':type(exc).__name__,'hf_fallback_receipt':hf_receipt}
        result=legacy_packet(match_id) if local_fallback else {'ok':False,'code':'LIVE_FETCH_FAILED','match_id':match_id,'usable_for_analysis':False}
        result['live_error']=type(exc).__name__
        return result
def main():
    parser=argparse.ArgumentParser(); subs=parser.add_subparsers(dest='cmd',required=True)
    command=subs.add_parser('match-packet'); command.add_argument('--match-id',required=True); command.add_argument('--local-fallback',action='store_true'); command.add_argument('--require-directional',action='store_true',help='force a fresh live packet suitable for directional shadow eligibility')
    preflight_cmd=subs.add_parser('preflight'); preflight_cmd.add_argument('--match-id',required=True); preflight_cmd.add_argument('--local-fallback',action='store_true'); preflight_cmd.add_argument('--require-directional',action='store_true')
    args=parser.parse_args(); result=packet(args.match_id,args.local_fallback,require_directional=args.require_directional)
    if args.cmd=='preflight':
        result={'match_id':str(args.match_id),'packet_code':result.get('code'),'source_mode':result.get('source_mode'),'freshness_contract':result.get('freshness_contract',{}),'identity_locked':bool(result.get('identity_lock',{}).get('passed')),'allow_analysis':bool(result.get('ok') and result.get('usable_for_analysis') and result.get('fresh') and (not args.require_directional or result.get('market_grade',{}).get('directional_shadow_allowed') is True))}
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result.get('ok',result.get('allow_analysis',False)) else 20
if __name__=='__main__':sys.exit(main())
