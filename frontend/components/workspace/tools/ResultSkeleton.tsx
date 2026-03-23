import { Skeleton } from "@/components/ui/skeleton";

export function ResultSkeleton({ 
  type = 'default' 
}: { 
  type?: 'default' | 'table' | 'cards' 
}) {
  if (type === 'table') {
    return (
      <div className="flex flex-col space-y-4 p-6 border border-border/50 rounded-2xl bg-card shadow-sm mt-6 w-full">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-[1px] w-full bg-border" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col space-y-4 p-6 border border-border/50 rounded-2xl bg-card shadow-sm mt-6 w-full animate-in fade-in duration-300">
      <div className="flex items-center space-x-4">
        <Skeleton className="h-20 w-20 rounded-xl" /> {/* 模拟图片占位 */}
        <div className="space-y-4 flex-1">
          <Skeleton className="h-4 w-[60%]" />
          <Skeleton className="h-4 w-[40%]" />
        </div>
      </div>
      <Skeleton className="h-[1px] w-full bg-border/50" /> {/* 分割线 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Skeleton className="h-12 w-full rounded-md" />
        <Skeleton className="h-12 w-full rounded-md" />
        <Skeleton className="h-12 w-full rounded-md" />
        <Skeleton className="h-12 w-full rounded-md" />
      </div>
    </div>
  );
}
