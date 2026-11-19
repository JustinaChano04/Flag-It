import { DecisionPage } from "./pages/DecisionPage";
import { QueuePage } from "./pages/QueuePage";
import { useRoute } from "./route";

export function App() {
  const route = useRoute();
  return (
    <>
      <header className="top">
        <a href="#/">Flag-It review</a>
      </header>
      <main>
        {route.page === "decision" ? (
          <DecisionPage key={route.decisionId} decisionId={route.decisionId} />
        ) : (
          <QueuePage />
        )}
      </main>
    </>
  );
}
