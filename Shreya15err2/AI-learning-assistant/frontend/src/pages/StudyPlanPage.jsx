import { useState } from "react";
import { api } from "../utils/api";

export default function StudyPlanPage() {
  const today = new Date();
  const defaultDate = new Date(today.setDate(today.getDate() + 14)).toISOString().split("T")[0];

  const [form, setForm] = useState({
    examDate: defaultDate,
    hoursPerDay: 3,
    subjects: "Mathematics, Physics",
    difficulty: "medium",
  });
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true); 
    setError(""); 
    setPlan(null);
    const subjects = form.subjects.split(",").map((s) => s.trim()).filter(Boolean);
    if (!subjects.length) { 
      setError("Please enter at least one subject."); 
      setLoading(false); 
      return; 
    }
    try {
      const res = await api.createStudyPlan(form.examDate, form.hoursPerDay, subjects, form.difficulty);
      setPlan(res);
    } catch (e) { 
      setError(e.message || "Failed to generate study plan."); 
    } finally { 
      setLoading(false); 
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-info">
          <h2>Study Planner</h2>
          <p>Generate a customized timeline to prep for your upcoming exams</p>
        </div>
      </div>
      
      <div className="page-content">
        <div className="card">
          <div className="card-header">
            <span className="card-title">📅 Exam & Study Details</span>
          </div>
          
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 14 }}>
            <div className="form-group">
              <label className="form-label">Exam date</label>
              <input 
                type="date" 
                className="form-input" 
                value={form.examDate} 
                onChange={(e) => setForm({ ...form, examDate: e.target.value })} 
              />
            </div>
            <div className="form-group">
              <label className="form-label">Available hours per day</label>
              <select 
                className="form-select" 
                value={form.hoursPerDay} 
                onChange={(e) => setForm({ ...form, hoursPerDay: +e.target.value })}
              >
                {[1, 2, 3, 4, 5, 6, 8].map((h) => <option key={h} value={h}>{h} hours</option>)}
              </select>
            </div>
          </div>
          
          <div className="form-group" style={{ marginBottom: 14 }}>
            <label className="form-label">Subjects to cover (comma separated)</label>
            <input 
              type="text" 
              className="form-input" 
              placeholder="e.g. Mathematics, Physics, Computer Science" 
              value={form.subjects} 
              onChange={(e) => setForm({ ...form, subjects: e.target.value })} 
            />
          </div>
          
          <div className="form-group" style={{ marginBottom: 16 }}>
            <label className="form-label">Difficulty Pace</label>
            <select 
              className="form-select" 
              value={form.difficulty} 
              onChange={(e) => setForm({ ...form, difficulty: e.target.value })}
            >
              <option value="easy">Easy — light review and spacing</option>
              <option value="medium">Medium — standard prep speed</option>
              <option value="hard">Hard — intensive high-speed schedule</option>
            </select>
          </div>
          
          <button className="btn btn-primary" onClick={generate} disabled={loading}>
            {loading ? (
              <>
                <div className="spinner" style={{ marginRight: 6 }} /> Constructing Plan...
              </>
            ) : (
              "📅 Generate Study Plan"
            )}
          </button>
        </div>

        {error && <div className="error-box">{error}</div>}

        {plan && (
          <div className="study-plan-results" style={{ marginTop: 20 }}>
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              <div className="card" style={{ flex: 1, padding: 16, textAlign: "center", marginBottom: 0 }}>
                <div style={{ fontSize: 28, fontWeight: 700, color: "var(--accent-light)" }}>{plan.total_days}</div>
                <div style={{ fontSize: 11, color: "var(--text3)", textTransform: "uppercase", letterSpacing: 0.5 }}>days remaining</div>
              </div>
              <div className="card" style={{ flex: 1, padding: 16, textAlign: "center", marginBottom: 0 }}>
                <div style={{ fontSize: 28, fontWeight: 700, color: "var(--green)" }}>{plan.total_hours.toFixed(0)}</div>
                <div style={{ fontSize: 11, color: "var(--text3)", textTransform: "uppercase", letterSpacing: 0.5 }}>total prep hours</div>
              </div>
            </div>

            {plan.tips && plan.tips.length > 0 && (
              <div className="card">
                <div className="card-header">
                  <span className="card-title">💡 Advisor Tips</span>
                </div>
                <ul className="key-points">
                  {plan.tips.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
            )}

            <div className="card">
              <div className="card-header">
                <span className="card-title">📆 Daily Study Schedule</span>
              </div>
              <div className="schedule-timeline" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {plan.plan.map((day, i) => (
                  <div key={i} className="plan-day">
                    <div className="plan-day-header">
                      <span className="plan-day-title">Day {day.day} · {day.subject}</span>
                      <span className="plan-day-hours">{day.hours} Hours</span>
                    </div>
                    <div className="plan-day-goal">{day.goal}</div>
                    {day.topics && day.topics.length > 0 && (
                      <div className="plan-topics">
                        {day.topics.map((t, j) => <span key={j} className="topic-chip">{t}</span>)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
