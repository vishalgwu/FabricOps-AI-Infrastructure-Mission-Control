export default function About() {
  return (
    <section>
      <h2>About FabricOps</h2>
      <p>
        FabricOps is an independent portfolio project: an evidence-grounded assistant for investigating simulated
        infrastructure incidents. It collects read-only telemetry, retrieves runbooks, asks a language model for
        hypotheses, and checks every claim against the evidence it was given.
      </p>
      <ul>
        <li>All data is synthetic. Nothing here touches real infrastructure.</li>
        <li>Hypotheses are suggestions for a human to review. They are not diagnoses.</li>
        <li>When evidence is stale or missing, FabricOps abstains and says what it needs.</li>
        <li>It only proposes next steps. It has no way to run them, and approving a proposal only records a decision.</li>
        <li>The reviewer name used for approvals is a demo stand-in, not real authentication.</li>
      </ul>
    </section>
  )
}
