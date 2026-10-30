import { Channel, invoke } from "@tauri-apps/api/core";
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
      width?: number;
      height?: number;
      output_dir?: string;
      original?: string;
      overlay?: string;
      summary?: ImageSummary;
    }
  | { event: "done"; total: number; output_root?: string; summary_csv?: string };

const IMAGE_EXTENSIONS = ["tif", "tiff", "png", "jpg", "jpeg", "bmp"];

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

async function readPng(path: string): Promise<Blob> {
  requireDesktop("Showing images");
  const bytes = await invoke<ArrayBuffer>("read_image", { path });
  return new Blob([bytes], { type: "image/png" });
}

/** A PNG written by the CLI, as a blob URL. The caller revokes it. */
export async function loadImage(path: string): Promise<string> {
  return URL.createObjectURL(await readPng(path));
}

/** A small thumbnail (blob URL) of a PNG written by the CLI. The caller revokes it. */
export async function loadThumbnail(path: string, width = 220): Promise<string> {
  // Scale on the canvas: WebKitGTK may ignore createImageBitmap's resize options.
  const bitmap = await createImageBitmap(await readPng(path));
  const scale = Math.min(1, width / bitmap.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const small = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!small) throw new Error("Could not make a thumbnail.");
  return URL.createObjectURL(small);
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
