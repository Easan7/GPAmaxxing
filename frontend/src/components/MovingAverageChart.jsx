import React from "react";
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

// Mapping your learning data to the chart
const learningData = [
  { day: "M", score: 60 },
  { day: "T", score: 35 },
  { day: "W", score: 90 }, 
  { day: "T", score: 55 },
  { day: "F", score: 30 },
  { day: "S", score: 65 },
  { day: "S", score: 40 },
];

export default function MovingAverageChart({ data = learningData }) {
  return (
    <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 w-full h-full min-h-[300px] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-gray-800 tracking-wide">Moving Average</h3>
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

            <Tooltip
              cursor={{ fill: "transparent" }}
              contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1)" }}
            />

            {/* Straight Rectangular Bars */}
            <Bar dataKey="score" barSize={16} radius={[4, 4, 4, 4]}>
              {data.map((entry, index) => (
                <Cell 
                  key={`cell-${index}`} 
                  fill={entry.score === 90 ? "#FF517F" : "#F3F4F6"} 
                />
              ))}
            </Bar>

            <Line
              type="monotone" // This creates the smooth cubic curve
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