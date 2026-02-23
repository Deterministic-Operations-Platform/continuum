import { Workflow } from './Workflow';
import { Logger } from './Logger';

export class Orchestrator {
  constructor(private logger = new Logger()) {}

  async run(workflow: Workflow, context: any = {}): Promise<void> {
    for (const step of workflow.steps) {
      let retries = 0;
      const maxRetries = (step as any).retries ?? 0;
      const backoff = (step as any).backoff ?? 1000;

      while (true) {
        try {
          this.logger.log(`Executing step: ${step.name}`);
          await step.execute(context);
          break;
        } catch (err) {
          this.logger.error(`Error in step ${step.name}: ${err}`);
          if (retries < maxRetries) {
            retries++;
            await new Promise((res) => setTimeout(res, backoff * retries));
          } else {
            throw err;
          }
        }
      }
    }
  }
}
