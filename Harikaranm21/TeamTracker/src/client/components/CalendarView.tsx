/**
 * CalendarView — monthly spreadsheet calendar.
 * Layout: rows = date groups (first ~15 days, then rest), columns = hours (00–23).
 * Sleep applies to ALL days in the month at once.
 * Click or drag cells to add events spanning multiple hours.
 * @module components/CalendarView
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box, Flex, Text, Button, Dialog,
  TextField, TextArea, Select, IconButton
} from '@radix-ui/themes';
import { CaretLeft, CaretRight, Moon, Plus, Trash } from '@phosphor-icons/react';
import type { CalendarEvent, CreateCalendarEventInput, CalendarEventType } from '../../shared/types';
import * as api from '../api';
import { useConfirm } from '../hooks/useConfirm';
import { useAuth } from '../hooks/useAuth';
import { exportCalendarToExcel } from '../utils/export';

// ── Constants ─────────────────────────────────────────────────────────────────

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const CELL_W = 48;        // px per hour cell
const LABEL_W = 80;       // px for date label column
const ROW_H = 40;         // px row height

const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December'
];
const WEEK_DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

const EVENT_COLORS: Record<CalendarEventType, string> = {
  meeting:  '#E5484D',
  task:     '#6E56CF',
  reminder: '#F76B15',
  other:    '#46A758',
};
const SLEEP_COLOR = '#3B82F6';

// ── Helpers ───────────────────────────────────────────────────────────────────

function pad2(n: number): string { return String(n).padStart(2,'0'); }
/** For storage — always 24h format: 22 → "22:00" */
function toTimeStr(h: number): string { return `${pad2(h)}:00`; }
/** For display — 12h AM/PM: 0→"12am", 13→"1pm" */
function to12h(h: number): string {
  if (h === 0)  return '12am';
  if (h === 12) return '12pm';
  return h < 12 ? `${h}am` : `${h-12}pm`;
}
function todayStr(): string { return new Date().toISOString().slice(0,10); }

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate(); // month is 1-indexed
}

function toDateStr(year: number, month: number, day: number): string {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}

function getWeekDay(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return WEEK_DAYS[d.getDay()];
}

/** Parse start hour and duration from event times. */
function getSpan(ev: CalendarEvent): { startH: number; span: number } {
  if (!ev.start_time) return { startH: 0, span: 1 };
  const startH = parseInt(ev.start_time, 10);
  if (!ev.end_time) return { startH, span: 1 };
  // '23:59' means "rest of day" — treat as hour 24
  const ep = ev.end_time.split(':');
  const endHour = parseInt(ep[0], 10);
  const endMin  = parseInt(ep[1] ?? '0', 10);
  const endH = endMin >= 59 ? endHour + 1 : endHour;
  return { startH, span: Math.max(1, Math.min(endH, 24) - startH) };
}

// ── Event Dialog ──────────────────────────────────────────────────────────────

interface EventDialogProps {
  open: boolean;
  event?: CalendarEvent;
  defaultDate?: string;
  defaultStart?: number;
  defaultEnd?: number;
  onSave: (input: CreateCalendarEventInput) => Promise<void>;
  onClose: () => void;
}

function EventDialog({ open, event, defaultDate, defaultStart, defaultEnd, onSave, onClose }: EventDialogProps): React.ReactElement {
  const [title, setTitle]       = useState('');
  const [desc, setDesc]         = useState('');
  const [type, setType]         = useState<CalendarEventType>('task');
  const [date, setDate]         = useState('');
  const [startH, setStartH]     = useState(9);
  const [endH, setEndH]         = useState(10);
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState('');

  useEffect(() => {
    if (!open) return;
    setTitle(event?.title ?? '');
    setDesc(event?.description ?? '');
    setType(event?.event_type ?? 'task');
    setDate(event?.date ?? defaultDate ?? todayStr());
    const sh = event?.start_time ? parseInt(event.start_time, 10) : (defaultStart ?? 9);
    const eh = event?.end_time   ? (() => { const p = event.end_time!.split(':'); return p[1]==='59'?parseInt(p[0],10)+1:parseInt(p[0],10); })() : (defaultEnd ?? sh + 1);
    setStartH(sh);
    setEndH(Math.max(sh + 1, eh));
    setError('');
  }, [open, event, defaultDate, defaultStart, defaultEnd]);

  const save = async (): Promise<void> => {
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true);
    try {
      await onSave({ title: title.trim(), description: desc, event_type: type, date,
        start_time: toTimeStr(startH), end_time: toTimeStr(endH), color: EVENT_COLORS[type] });
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed'); }
    finally { setSaving(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Content style={{ maxWidth: 440 }}>
        <Dialog.Title>{event ? 'Edit Event' : 'New Event'}</Dialog.Title>
        <Flex direction="column" gap="3" mt="3">
          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="ev-t">Title *</Text>
            <TextField.Root id="ev-t" mt="1" placeholder="Event title" value={title} onChange={e=>setTitle(e.target.value)} />
          </Box>
          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="ev-d">Description</Text>
            <TextArea id="ev-d" mt="1" placeholder="Notes" value={desc} onChange={e=>setDesc(e.target.value)} rows={2} />
          </Box>
          <Flex gap="3">
            <Box style={{ flex:1 }}>
              <Text as="label" size="2" weight="medium">Type</Text>
              <Select.Root value={type} onValueChange={v=>setType(v as CalendarEventType)}>
                <Select.Trigger mt="1" style={{ width:'100%' }} />
                <Select.Content>
                  <Select.Item value="task">Task</Select.Item>
                  <Select.Item value="meeting">Meeting</Select.Item>
                  <Select.Item value="reminder">Reminder</Select.Item>
                  <Select.Item value="other">Other</Select.Item>
                </Select.Content>
              </Select.Root>
            </Box>
            <Box style={{ flex:1 }}>
              <Text as="label" size="2" weight="medium" htmlFor="ev-dt">Date</Text>
              <TextField.Root id="ev-dt" mt="1" type="date" value={date} onChange={e=>setDate(e.target.value)} />
            </Box>
          </Flex>
          <Flex gap="3">
            <Box style={{ flex:1 }}>
              <Text as="label" size="2" weight="medium">Start</Text>
              <Select.Root value={String(startH)} onValueChange={v=>{ const h=Number(v); setStartH(h); if(endH<=h) setEndH(h+1); }}>
                <Select.Trigger mt="1" style={{ width:'100%' }} />
                <Select.Content>
                  {HOURS.map(h=><Select.Item key={h} value={String(h)}>{to12h(h)}</Select.Item>)}
                </Select.Content>
              </Select.Root>
            </Box>
            <Box style={{ flex:1 }}>
              <Text as="label" size="2" weight="medium">End</Text>
              <Select.Root value={String(endH)} onValueChange={v=>setEndH(Number(v))}>
                <Select.Trigger mt="1" style={{ width:'100%' }} />
                <Select.Content>
                  {HOURS.filter(h=>h>startH).map(h=><Select.Item key={h} value={String(h)}>{to12h(h)}</Select.Item>)}
                </Select.Content>
              </Select.Root>
            </Box>
          </Flex>
          <Text size="1" color="gray">{endH-startH} hour{endH-startH!==1?'s':''} · {to12h(startH)}–{to12h(endH)}</Text>
          {error && <Text size="2" color="red">{error}</Text>}
        </Flex>
        <Flex gap="3" mt="4" justify="end">
          <Dialog.Close><Button variant="soft" color="gray" onClick={onClose}>Cancel</Button></Dialog.Close>
          <Button onClick={save} loading={saving}>{event ? 'Save' : 'Add Event'}</Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}

// ── Sleep Dialog ──────────────────────────────────────────────────────────────

interface SleepDialogProps {
  open: boolean;
  monthName: string;
  onApply: (sleepStart: number, wakeEnd: number) => Promise<void>;
  onClose: () => void;
}

function SleepDialog({ open, monthName, onApply, onClose }: SleepDialogProps): React.ReactElement {
  const [sleepH, setSleepH] = useState(22); // 10 PM
  const [wakeH, setWakeH]   = useState(8);  // 8 AM
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { if (open) setError(''); }, [open]);

  const handleApply = async (): Promise<void> => {
    setApplying(true);
    try { await onApply(sleepH, wakeH); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed'); }
    finally { setApplying(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Content style={{ maxWidth: 380 }}>
        <Dialog.Title>
          <Flex align="center" gap="2"><Moon size={16} /><Text>Set Sleep Schedule for This Month</Text></Flex>
        </Dialog.Title>
        <Text size="2" color="gray" mb="3" style={{ display:'block' }}>
          This will add sleep blocks to <strong>every day</strong> in the current month.
          Existing sleep blocks won't be duplicated.
        </Text>
        <Flex gap="3" mt="3">
          <Box style={{ flex:1 }}>
            <Text as="label" size="2" weight="medium">Sleep time</Text>
            <Select.Root value={String(sleepH)} onValueChange={v=>setSleepH(Number(v))}>
              <Select.Trigger mt="1" style={{ width:'100%' }} />
              <Select.Content>
                {HOURS.map(h=><Select.Item key={h} value={String(h)}>{to12h(h)}</Select.Item>)}
              </Select.Content>
            </Select.Root>
          </Box>
          <Box style={{ flex:1 }}>
            <Text as="label" size="2" weight="medium">Wake time</Text>
            <Select.Root value={String(wakeH)} onValueChange={v=>setWakeH(Number(v))}>
              <Select.Trigger mt="1" style={{ width:'100%' }} />
              <Select.Content>
                {HOURS.map(h=><Select.Item key={h} value={String(h)}>{to12h(h)}</Select.Item>)}
              </Select.Content>
            </Select.Root>
          </Box>
        </Flex>
        <Text size="1" color="gray" mt="2" style={{ display:'block' }}>
          Tonight: {to12h(sleepH)}–midnight · Tomorrow morning: midnight–{to12h(wakeH)}
        </Text>
        {error && <Text size="2" color="red" mt="2">{error}</Text>}
        <Flex gap="3" mt="4" justify="end">
          <Dialog.Close><Button variant="soft" color="gray" onClick={onClose}>Cancel</Button></Dialog.Close>
            <Button color="blue" onClick={handleApply} loading={applying}>
            Apply to all {monthName} days
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}

// ── Grid Row ──────────────────────────────────────────────────────────────────

interface RowProps {
  dateStr: string;
  events: CalendarEvent[];
  onDragSelect: (date: string, sh: number, eh: number) => void;
  onEdit: (ev: CalendarEvent) => void;
  onDelete: (id: number) => void;
}

function GridRow({ dateStr, events, onDragSelect, onEdit, onDelete }: RowProps): React.ReactElement {
  const wd = getWeekDay(dateStr);
  const dayNum = parseInt(dateStr.split('-')[2], 10);
  const isToday = dateStr === todayStr();
  const isWeekend = wd === 'Sun' || wd === 'Sat';

  // drag state — use useState so highlight re-renders
  const [dragSH, setDragSH] = useState<number|null>(null);
  const [dragEH, setDragEH] = useState<number|null>(null);
  const pressing = useRef(false);

  const dragMin = dragSH!==null && dragEH!==null ? Math.min(dragSH,dragEH) : null;
  const dragMax = dragSH!==null && dragEH!==null ? Math.max(dragSH,dragEH) : null;

  // occupied map
  const occ: Record<number,{ev:CalendarEvent;isStart:boolean}> = {};
  events.forEach(ev => {
    const {startH, span} = getSpan(ev);
    for (let h=startH; h<Math.min(startH+span,24); h++) occ[h]={ev,isStart:h===startH};
  });

  const onMD = (h:number, e:React.MouseEvent) => {
    if (occ[h]) return;
    e.preventDefault(); pressing.current=true; setDragSH(h); setDragEH(h);
  };
  const onME = (h:number) => { if(!pressing.current) return; setDragEH(h); };
  const onMU = (h:number) => {
    if(!pressing.current || dragSH===null) return;
    pressing.current=false;
    const sh=Math.min(dragSH,h); const eh=Math.max(dragSH,h)+1;
    setDragSH(null); setDragEH(null);
    onDragSelect(dateStr, sh, eh);
  };
  const onML = () => {
    if(!pressing.current || dragSH===null || dragEH===null) return;
    pressing.current=false;
    const sh=Math.min(dragSH,dragEH); const eh=Math.max(dragSH,dragEH)+1;
    setDragSH(null); setDragEH(null);
    onDragSelect(dateStr, sh, eh);
  };

  // Build cells
  const cells: React.ReactElement[] = [];
  const done = new Set<number>();
  for (let h=0; h<24; h++) {
    if (done.has(h)) continue;
    const slot = occ[h];
    if (slot?.isStart) {
      const {ev} = slot;
      const {startH, span} = getSpan(ev);
      const isSleep = ev.title==='Sleep';
      const col = isSleep ? SLEEP_COLOR : ev.color;
      for (let s=startH; s<Math.min(startH+span,24); s++) done.add(s);
      cells.push(
        <Flex key={`ev${ev.id}`} align="center" gap="1"
          style={{ width:CELL_W*span-2, minWidth:CELL_W*span-2, height:ROW_H-8,
            background:col+'25', borderLeft:`3px solid ${col}`,
            borderRadius:4, padding:'0 6px', overflow:'hidden',
            flexShrink:0, marginRight:2, cursor:'pointer', userSelect:'none' }}
          onClick={()=>onEdit(ev)}>
          {isSleep && <Moon size={10} style={{color:col,flexShrink:0}} />}
          <Text size="1" style={{flex:1,overflow:'hidden',textOverflow:'ellipsis',
            whiteSpace:'nowrap',color:col,fontWeight:600}}>
            {ev.title}
          </Text>
          <IconButton size="1" variant="ghost" color="red" style={{flexShrink:0,opacity:.7}}
            onClick={e2=>{e2.stopPropagation();onDelete(ev.id);}} title="Delete">
            <Trash size={9}/>
          </IconButton>
        </Flex>
      );
    } else {
      done.add(h);
      const inDrag = dragMin!==null && dragMax!==null && h>=dragMin && h<=dragMax;
      cells.push(
        <Box key={`c${h}`}
          style={{ width:CELL_W-2, minWidth:CELL_W-2, height:ROW_H-8,
            borderRadius:3, flexShrink:0, marginRight:2, cursor:'crosshair',
            background: inDrag?'var(--accent-a5)':'var(--gray-a2)',
            border: inDrag?'1px dashed var(--accent-8)':'1px solid var(--gray-a3)',
            transition:'background 0.07s', userSelect:'none' }}
          onMouseDown={e=>onMD(h,e)} onMouseEnter={()=>onME(h)} onMouseUp={()=>onMU(h)} />
      );
    }
  }

  return (
    <Flex align="center"
      style={{ borderBottom:'1px solid var(--gray-a3)', minHeight:ROW_H, minWidth: LABEL_W + CELL_W * 25,
        background: isWeekend?'var(--gray-a2)':isToday?'var(--accent-a1)':'transparent' }}
      onMouseLeave={onML}>
      {/* Date label */}
      <Flex align="center" justify="center" direction="column"
        style={{ width:LABEL_W, minWidth:LABEL_W, flexShrink:0, padding:'4px 6px',
          borderRight:'1px solid var(--gray-a4)', textAlign:'center' }}>
        <Text size="1" weight={isToday?'bold':'regular'}
          style={{ color: isToday?'var(--accent-9)':isWeekend?'var(--red-10)':'inherit' }}>
          {wd} {dayNum}
        </Text>
      </Flex>
      {/* Cells */}
      <Flex align="center" style={{ flex:1, padding:'4px 4px 4px 2px', gap:0, userSelect:'none', minWidth: CELL_W * 25 }}>
        {cells}
      </Flex>
    </Flex>
  );
}

// ── Main CalendarView ─────────────────────────────────────────────────────────

export function CalendarView(): React.ReactElement {
  const now = new Date();
  const [year, setYear]   = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth()+1); // 1-indexed
  const [events, setEvents]   = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen]     = useState(false);
  const [sleepDialogOpen, setSleepOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent|undefined>();
  const [dialogDate, setDialogDate]     = useState('');
  const [dialogSH, setDialogSH]         = useState(9);
  const [dialogEH, setDialogEH]         = useState(10);
  const { confirm, ConfirmDialog }      = useConfirm();
  const { user }                        = useAuth();

  // All days in this month
  const totalDays  = daysInMonth(year, month);
  const allDates   = Array.from({length:totalDays},(_,i)=>toDateStr(year,month,i+1));
  // Split: first 15, then rest
  const row1 = allDates.slice(0, 15);
  const row2 = allDates.slice(15);

  const loadMonth = useCallback(async () => {
    try {
      const data = await api.fetchCalendarMonth(year, month);
      setEvents(data);
    } catch { setEvents([]); }
  }, [year, month]);

  useEffect(() => {
    setLoading(true);
    loadMonth().finally(()=>setLoading(false));
  }, [loadMonth]);

  const prevMonth = () => { if(month===1){setYear(y=>y-1);setMonth(12);}else setMonth(m=>m-1); };
  const nextMonth = () => { if(month===12){setYear(y=>y+1);setMonth(1);}else setMonth(m=>m+1); };
  const goToday   = () => { setYear(now.getFullYear()); setMonth(now.getMonth()+1); };

  const openAdd = (date:string, sh=9, eh=10) => {
    setEditingEvent(undefined); setDialogDate(date);
    setDialogSH(sh); setDialogEH(eh); setDialogOpen(true);
  };
  const openEdit = (ev:CalendarEvent) => {
    setEditingEvent(ev); setDialogDate(ev.date);
    const {startH,span}=getSpan(ev); setDialogSH(startH); setDialogEH(startH+span);
    setDialogOpen(true);
  };

  const handleSave = async (input:CreateCalendarEventInput) => {
    if (editingEvent) {
      const updated = await api.updateCalendarEvent(editingEvent.id, input);
      setEvents(prev=>prev.map(e=>e.id===updated.id?updated:e));
    } else {
      const created = await api.createCalendarEvent(input);
      setEvents(prev=>[...prev,created]);
    }
  };

  const handleDelete = async (id:number) => {
    const ok = await confirm({title:'Delete event',description:'This event will be permanently deleted.',confirmLabel:'Delete'});
    if(!ok) return;
    await api.deleteCalendarEvent(id);
    setEvents(prev=>prev.filter(e=>e.id!==id));
  };

  // Apply sleep to ALL days in the current month
  const handleApplySleep = async (sleepH:number, wakeH:number) => {
    // First delete any existing sleep events for this month
    const existingSleep = events.filter(e => e.title === 'Sleep');
    if (existingSleep.length > 0) {
      await Promise.all(existingSleep.map(e => api.deleteCalendarEvent(e.id)));
      setEvents(prev => prev.filter(e => e.title !== 'Sleep'));
    }

    const toCreate: CreateCalendarEventInput[] = [];
    // Night block on each day: sleepH → 23 (spans sleepH to end of day)
    // Morning block on each day: 0 → wakeH (spans start of day to wakeH)
    allDates.forEach((date) => {
      // Night: e.g. 22:00–23:59 on this date
      toCreate.push({
        title: 'Sleep', description: 'Sleep', event_type: 'other',
        date, start_time: toTimeStr(sleepH), end_time: '23:59', color: SLEEP_COLOR
      });
      // Morning: e.g. 00:00–08:00 on this same date
      toCreate.push({
        title: 'Sleep', description: 'Sleep', event_type: 'other',
        date, start_time: '00:00', end_time: toTimeStr(wakeH), color: SLEEP_COLOR
      });
    });

    const created = await Promise.all(toCreate.map(i => api.createCalendarEvent(i)));
    setEvents(prev => [...prev, ...created]);
  };

  const eventsForDate = (d:string) => events.filter(e=>e.date===d);

  // Hour header — shared for both grids
  const HourHeader = () => (
    <Flex style={{ position:'sticky', top:0, zIndex:10,
      background:'var(--color-panel-solid)', borderBottom:'2px solid var(--gray-a4)' }}>
      <Box style={{ width:LABEL_W, minWidth:LABEL_W, flexShrink:0, borderRight:'1px solid var(--gray-a4)' }} />
      <Flex style={{ padding:'3px 2px', minWidth: CELL_W * 25 }}>
        {HOURS.map(h=>(
          <Box key={h} style={{ width:CELL_W-2, minWidth:CELL_W-2, textAlign:'center', flexShrink:0, marginRight:2 }}>
            <Text size="1" color="gray">{to12h(h)}</Text>
          </Box>
        ))}
      </Flex>
    </Flex>
  );

  return (
    <Flex direction="column" style={{ height:'100%', overflow:'hidden' }}>
      {ConfirmDialog}

      {/* Top bar */}
      <Flex justify="between" align="center" mb="3" style={{ flexShrink:0 }}>
        <Text size="5" weight="bold">My Calendar</Text>
        <Flex align="center" gap="2">
          <IconButton variant="ghost" color="gray" title="Previous month" onClick={prevMonth}><CaretLeft size={16}/></IconButton>
          <Text size="3" weight="medium" style={{ minWidth:180, textAlign:'center' }}>
            {MONTHS[month-1]} {year}
          </Text>
          <IconButton variant="ghost" color="gray" title="Next month" onClick={nextMonth}><CaretRight size={16}/></IconButton>
          <Button size="2" variant="soft" onClick={goToday}>Today</Button>
          <Button size="2" color="blue" variant="soft" onClick={()=>setSleepOpen(true)}>
            <Moon size={14}/> Set Sleep
          </Button>
          <Button size="2" onClick={()=>openAdd(todayStr())}>
            <Plus size={14}/> Add Event
          </Button>
          <Button size="2" variant="soft" color="green"
            onClick={() => exportCalendarToExcel(events, year, month, user?.username ?? 'calendar')}>
            ↓ Export Excel
          </Button>
        </Flex>
      </Flex>

      {/* Legend */}
      <Flex gap="3" mb="2" align="center" style={{ flexShrink:0, flexWrap:'wrap' }}>
        {([['task','Task'],['meeting','Meeting'],['reminder','Reminder'],['other','Other']] as [CalendarEventType,string][]).map(([t,l])=>(
          <Flex key={t} align="center" gap="1">
            <Box style={{ width:10, height:10, borderRadius:2, background:EVENT_COLORS[t] }}/>
            <Text size="1" color="gray">{l}</Text>
          </Flex>
        ))}
        <Flex align="center" gap="1">
          <Moon size={10} style={{ color:SLEEP_COLOR }}/>
          <Text size="1" color="gray">Sleep</Text>
        </Flex>
        <Text size="1" color="gray" style={{ marginLeft:'auto' }}>
          Click cell to add · Drag across hours to span multiple hours
        </Text>
      </Flex>

      {/* Two grids */}
      {loading ? (
        <Flex align="center" justify="center" style={{ flex:1 }}>
          <Text color="gray">Loading…</Text>
        </Flex>
      ) : (
        <Flex direction="column" gap="4" style={{ flex:1, overflowY:'auto' }}>
          {/* Row group 1: days 1–15 */}
          <Box>
            <Text size="2" weight="medium" mb="1" style={{ display:'block', color:'var(--gray-11)' }}>
              Days 1–{row1.length}
            </Text>
            <Box style={{ overflowX:'auto', border:'1px solid var(--gray-a4)', borderRadius:'var(--radius-3)' }}>
              <HourHeader/>
              {row1.map(d=>(
                <GridRow key={d} dateStr={d} events={eventsForDate(d)}
                  onDragSelect={(date,sh,eh)=>openAdd(date,sh,eh)}
                  onEdit={openEdit} onDelete={handleDelete}/>
              ))}
            </Box>
          </Box>

          {/* Row group 2: days 16–end */}
          {row2.length > 0 && (
            <Box>
              <Text size="2" weight="medium" mb="1" style={{ display:'block', color:'var(--gray-11)' }}>
                Days {row1.length+1}–{totalDays}
              </Text>
              <Box style={{ overflowX:'auto', border:'1px solid var(--gray-a4)', borderRadius:'var(--radius-3)' }}>
                <HourHeader/>
                {row2.map(d=>(
                  <GridRow key={d} dateStr={d} events={eventsForDate(d)}
                    onDragSelect={(date,sh,eh)=>openAdd(date,sh,eh)}
                    onEdit={openEdit} onDelete={handleDelete}/>
                ))}
              </Box>
            </Box>
          )}
        </Flex>
      )}

      <EventDialog open={dialogOpen} event={editingEvent}
        defaultDate={dialogDate} defaultStart={dialogSH} defaultEnd={dialogEH}
        onSave={handleSave} onClose={()=>setDialogOpen(false)}/>

      <SleepDialog open={sleepDialogOpen} monthName={MONTHS[month-1]}
        onApply={handleApplySleep} onClose={()=>setSleepOpen(false)}/>
    </Flex>
  );
}
