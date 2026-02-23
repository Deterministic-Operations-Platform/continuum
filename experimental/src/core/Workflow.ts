import { Step } from './Step';

export class Workflow {
  constructor(public name: string, public steps: Step[]) {}
}
