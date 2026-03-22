import { FlaskConical } from "lucide-react";

export default function GlobalLoading() {
  return (
    // 纯白底色，绝对居中
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-white dark:bg-zinc-950">
      <div className="relative flex items-center justify-center">
        {/* 呼吸发光层 */}
        <div className="absolute inset-0 rounded-full bg-blue-100 dark:bg-blue-900/30 blur-xl animate-pulse" />
        {/* 品牌 Icon 旋转/呼吸 */}
        <FlaskConical size={48} className="text-blue-600 dark:text-blue-500 relative z-10 animate-bounce" strokeWidth={1.5} />
      </div>
      <h2 className="mt-6 text-lg font-medium text-slate-600 dark:text-slate-400 tracking-widest animate-pulse">
        CHEM<span className="font-bold text-slate-900 dark:text-slate-100">AGENT</span>
      </h2>
    </div>
  );
}
