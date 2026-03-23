import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface LoadingButtonProps extends React.ComponentProps<typeof Button> {
  isLoading: boolean;
  loadingText?: string;
  hasIcon?: boolean;
}

export function LoadingButton({ 
  isLoading, 
  loadingText = "处理中...", 
  children, 
  hasIcon = false,
  ...props 
}: LoadingButtonProps) {
  return (
    <Button disabled={isLoading} {...props}>
      {isLoading ? (
        <>
          <Loader2 className={`mr-2 h-4 w-4 animate-spin ${hasIcon ? 'mr-2' : ''}`} />
          {loadingText}
        </>
      ) : (
        children
      )}
    </Button>
  );
}
