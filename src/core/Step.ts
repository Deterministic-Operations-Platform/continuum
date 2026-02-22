export interface Step {
  name: string;
  execute(context: any): Promise<void>;
}
