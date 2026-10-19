export type Route =
  | { name: "home" }
  | { name: "opportunity"; id: string; focus?: "profile_input" }
  | { name: "planner" }
  | { name: "academics" }
  | {
      name: "course";
      id: string;
      tab?: "assignments" | "materials" | "announcements" | "syllabus";
    }
  | { name: "documents" }
  | { name: "upload" }
  | { name: "notifications" }
  | { name: "settings" }
  | { name: "onboarding" };

export type Tone = "blue" | "green" | "yellow" | "red" | "gray";
