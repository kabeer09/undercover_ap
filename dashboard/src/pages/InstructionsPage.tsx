import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const claim = useLoad(api.getInstructions);
  const queue = useLoad(api.getQueueInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        What the agent reads before it works the queue and each claim. This page
        is read only.
      </p>
      <h2>Working the queue</h2>
      <section className="panel">
        {queue.data ? (
          <pre className="instructions">{queue.data.text}</pre>
        ) : (
          <Message error={queue.error} />
        )}
      </section>
      <h2>Working a claim</h2>
      <section className="panel">
        {claim.data ? (
          <pre className="instructions">{claim.data.text}</pre>
        ) : (
          <Message error={claim.error} />
        )}
      </section>
    </>
  );
}
