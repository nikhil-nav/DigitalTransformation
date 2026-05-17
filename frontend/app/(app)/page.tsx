import ProjectList from "@/components/ProjectList";
import ProjectTypesPanel from "@/components/ProjectTypesPanel";
import { listProjectTypesServer } from "@/lib/api-server";

export default async function HomePage() {
  const types = await listProjectTypesServer();

  return (
    <div className="stack">
      <ProjectTypesPanel types={types} />
      <ProjectList />
    </div>
  );
}
