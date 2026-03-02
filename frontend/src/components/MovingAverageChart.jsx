import React, { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { hasSupabaseConfig, supabase } from "../lib/supabaseClient";

const DAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"];

function startOfDayLocal(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function addDaysLocal(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function getLast7DaysRangeLocal() {
  const todayStart = startOfDayLocal(new Date());
  const start = addDaysLocal(todayStart, -6);
  const end = addDaysLocal(todayStart, 1);
  return { start, end };
}

function buildLast7DaysSkeleton() {
  const todayStart = startOfDayLocal(new Date());

  // oldest -> newest (6 days ago ... today)
  return Array.from({ length: 7 }).map((_, i) => {
    const date = addDaysLocal(todayStart, i - 6);
    const day = DAY_LETTERS[date.getDay()];
    return {
      day,
      dateKey: date.toISOString().slice(0, 10),
      score: null,
      attempts: 0,
      correct: 0,
    };
  });
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div
      style={{
        background: "white",
        borderRadius: 12,
        padding: "10px 12px",
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1)",
        fontSize: 12,
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 6 }}>
        {label} <span style={{ color: "#9CA3AF" }}>({p.dateKey})</span>
      </div>
      <div>
        Accuracy: <b>{p.score == null ? "—" : `${Math.round(p.score)}%`}</b>
      </div>
      <div>
        Attempts: <b>{p.attempts}</b>
      </div>
      <div>
        Correct: <b>{p.correct}</b>
      </div>
    </div>
  );
}

export default function MovingAverageChart({ studentId }) {
  const [data, setData] = useState(buildLast7DaysSkeleton());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const highlightMaxIndex = useMemo(() => {
    let bestIdx = -1;
    let bestVal = -Infinity;
    data.forEach((d, idx) => {
      if (typeof d.score === "number" && d.score > bestVal) {
        bestVal = d.score;
        bestIdx = idx;
      }
    });
    return bestIdx;
  }, [data]);

  useEffect(() => {
    if (!studentId) return;

    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");

      if (!hasSupabaseConfig || !supabase) {
        setError("Supabase is not configured. Add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
        setData(buildLast7DaysSkeleton());
        setLoading(false);
        return;
      }

      const skeleton = buildLast7DaysSkeleton();
      const { start, end } = getLast7DaysRangeLocal();

      const { data: rows, error: supaErr } = await supabase
        .from("attempts")
        .select("attempted_at, correct")
        .eq("student_id", studentId)
        .gte("attempted_at", start.toISOString())
        .lt("attempted_at", end.toISOString());

      if (cancelled) return;

      if (supaErr) {
        setError(supaErr.message || "Failed to load attempts");
        setData(skeleton);
        setLoading(false);
        return;
      }

      const indexByDateKey = new Map();
      skeleton.forEach((d, idx) => indexByDateKey.set(d.dateKey, idx));

      for (const r of rows || []) {
        const dt = new Date(r.attempted_at);
        const localKey = startOfDayLocal(dt).toISOString().slice(0, 10);

        const idx = indexByDateKey.get(localKey);
        if (idx == null) continue;

        skeleton[idx].attempts += 1;
        if (r.correct) skeleton[idx].correct += 1;
      }

      const final = skeleton.map((d) => {
        if (d.attempts === 0) return { ...d, score: null };
        return { ...d, score: (d.correct / d.attempts) * 100 };
      });

      setData(final);
      setLoading(false);
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [studentId]);

  return (
    <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 w-full h-full min-h-[300px] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-gray-800 tracking-wide">
          Moving Average
        </h3>
        {loading ? (
          <span className="text-xs font-semibold text-gray-400">Loading…</span>
        ) : error ? (
          <span className="text-xs font-semibold text-red-500">{error}</span>
        ) : (
          <span className="text-xs font-semibold text-gray-400">Last 7 days</span>
        )}
      </div>

      <div className="flex-1 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#F3F2EE" vertical={false} strokeWidth={2} />

            <XAxis
              dataKey="day"
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#9CA3AF", fontSize: 10, fontWeight: 700 }}
              dy={10}
            />

            <YAxis hide domain={[0, 100]} />

            <Tooltip cursor={{ fill: "transparent" }} content={<CustomTooltip />} />

            <Bar dataKey="score" barSize={16} radius={[4, 4, 4, 4]}>
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={
                    entry.score == null
                      ? "#F9FAFB"
                      : index === highlightMaxIndex
                        ? "#FF517F"
                        : "#F3F4F6"
                  }
                />
              ))}
            </Bar>

            <Line
              type="monotone"
              dataKey="score"
              stroke="#1F2937"
              strokeWidth={3}
              dot={false}
              activeDot={{ r: 6, fill: "#FF517F", stroke: "#fff", strokeWidth: 2 }}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}