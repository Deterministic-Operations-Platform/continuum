export class StepRegistry {
  private registry = new Map<string, any>();

  register(name: string, cls: new (...args: any[]) => any) {
    this.registry.set(name, cls);
  }

  get(name: string): new (...args: any[]) => any | undefined {
    return this.registry.get(name);
  }
}
