import { notFound } from "next/navigation";

import ProjectDetail from "@/components/ProjectDetail";

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const projectId = Number(id);
  if (!Number.isInteger(projectId) || projectId <= 0) {
    notFound();
  }
  return <ProjectDetail projectId={projectId} />;
}
