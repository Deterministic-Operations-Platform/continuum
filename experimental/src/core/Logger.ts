export class Logger {
  log(message: string): void {
    console.log(`[INFO] ${message}`);
  }
  warn(message: string): void {
    console.warn(`[WARN] ${message}`);
  }
  error(message: string): void {
    console.error(`[ERROR] ${message}`);
  }
}
