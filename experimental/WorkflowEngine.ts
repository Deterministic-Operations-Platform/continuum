import { Context } from './Context';
import { Step } from './Step';
import { Logger } from './Logger';

export class WorkflowEngine {
  private steps: Step[] = [];
  private logger: Logger = new Logger();

  addStep(step: Step) {
    this.steps.push(step);
  }

  async run(initialContext: Context): Promise<void> {
    const context = { ...initialContext };

    for (const step of this.steps) {
      try {
        this.logger.log(`Executing step: ${step.name}`);
        await step.execute(context);
      } catch (error) {
        this.logger.error(`Step failed: ${step.name}, Error: ${error}`);
      }
    }
  }
}