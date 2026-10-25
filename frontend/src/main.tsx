import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { App } from "./App";
import { ApiError } from "./api/client";
import "./styles.css";
import "./tailwind.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry once on a network or server error; asking again won't change a 4xx answer.
      retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status < 500),
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <App />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
