import { Channel, convertFileSrc, invoke } from "@tauri-apps/api/core";
import { homeDir } from "@tauri-apps/api/path";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open } from "@tauri-apps/plugin-dialog";

import type { ImageSummary } from "./stats";

/** JSON lines printed by `eyespysc --json-progress`. */
export type CliEvent =
  | { event: "start"; total: number; preview_only: boolean }
  | {
      event: "image";
      index: number;
      total: number;
      name: string;
      image: string;
      preview?: string;
      thumb?: string;
      width?: number;
      height?: number;
      output_dir?: string;
      original?: string;
      overlay?: string;
      summary?: ImageSummary;
    }
  | { event: "done"; total: number; output_root?: string; summary_csv?: string };

// Same list as IMAGE_EXTENSIONS in backend/src/eyespysc/sperm_count.py, which
// matches extensions in any letter case.
const IMAGE_EXTENSIONS = ["tif", "tiff", "png", "jpg", "jpeg", "bmp"];

export const ACCEPTED_TYPES_TEXT = "TIFF (.tif, .tiff), PNG, JPEG (.jpg, .jpeg) and BMP";

export function isDesktopShell() {
  return "__TAURI_INTERNALS__" in window;
}

function requireDesktop(action: string) {
  if (!isDesktopShell()) throw new Error(`${action} is available in the desktop application.`);
}

export async function chooseFolder(title: string): Promise<string | null> {
  requireDesktop("Choosing folders");
  return open({ title, directory: true });
}

export async function chooseImages(): Promise<string[] | null> {
  requireDesktop("Choosing images");
  const selected = await open({
    title: "Choose images to count",
    multiple: true,
    filters: [
      {
        name: "Microscope images",
        extensions: [...IMAGE_EXTENSIONS, ...IMAGE_EXTENSIONS.map((ext) => ext.toUpperCase())],
      },
    ],
  });
  if (selected === null) return null;
  return Array.isArray(selected) ? selected : [selected];
}

export async function homeFolder(): Promise<string> {
  requireDesktop("Finding the home folder");
  return (await homeDir()).replace(/\/+$/, "");
}

export async function previewImages(inputs: string[], onEvent: (event: CliEvent) => void) {
  requireDesktop("Loading images");
  const channel = new Channel<CliEvent>();
  channel.onmessage = onEvent;
  await invoke("preview_images", { inputs, onEvent: channel });
}

export async function countSperm(
  inputs: string[],
  outputRoot: string,
  onEvent: (event: CliEvent) => void,
) {
  requireDesktop("Counting");
  const channel = new Channel<CliEvent>();
  channel.onmessage = onEvent;
  await invoke("count_sperm", { inputs, outputRoot, onEvent: channel });
}

/** URL the window can load a PNG from. Rust allows only the preview and results folders. */
export function imageUrl(path: string): string {
  return convertFileSrc(path);
}

export async function openDirectory(path: string): Promise<void> {
  requireDesktop("Opening folders");
  await invoke("open_directory", { path });
}

export async function startMainWindowDragging(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().startDragging();
}

export async function minimizeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().minimize();
}

export async function toggleMaximizeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().toggleMaximize();
}

export async function closeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().close();
}

export async function isMainWindowMaximized(): Promise<boolean> {
  if (!isDesktopShell()) return false;
  return getCurrentWindow().isMaximized();
}
