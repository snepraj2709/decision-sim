import { api } from "@/lib/api";
import { DashboardClient } from "./client";

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ simulationId: string }>;
}) {
  const { simulationId } = await params;
  const simulation = await api.getSimulation(simulationId);
  const segments = await api.getSegments(simulation.snapshot_id);

  return <DashboardClient simulation={simulation} segments={segments} />;
}
