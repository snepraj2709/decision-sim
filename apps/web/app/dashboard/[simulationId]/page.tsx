import { api } from "@/lib/api";
import { DashboardClient } from "./client";

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ simulationId: string }>;
}) {
  const { simulationId } = await params;
  try {
    const simulation = await api.getSimulation(simulationId);
    const segments = await api.getSegments(simulation.snapshot_id);

    return <DashboardClient simulation={simulation} segments={segments} />;
  } catch {
    return (
      <main className="min-h-screen px-6 py-16">
        <div className="mx-auto max-w-xl">
          <h2 className="mb-3 text-2xl font-semibold">Simulation not found</h2>
          <p className="mb-6 text-sm text-neutral-600">
            This simulation may have been deleted or the ID is incorrect.
          </p>
          <a
            href="/compose"
            className="inline-flex rounded bg-neutral-950 px-4 py-2 text-sm font-medium text-white"
          >
            Start a new simulation
          </a>
        </div>
      </main>
    );
  }
}
