import fs from 'fs';
import yaml from 'js-yaml';
import { Workflow } from '../core/Workflow';
import { StepRegistry } from '../registry/StepRegistry';
import { Step } from '../core/Step';

// Substitute environment variables in strings and recursively handle objects/arrays
function substituteEnv(value: any): any {
  if (typeof value === 'string') {
    return value.replace(/\$\{([^}]+)\}/g, (_, varName) => process.env[varName] || '');
  } else if (Array.isArray(value)) {
    return value.map((v) => substituteEnv(v));
  } else if (value && typeof value === 'object') {
    const res: any = {};
    for (const key of Object.keys(value)) {
      res[key] = substituteEnv((value as any)[key]);
    }
    return res;
  }
  return value;
}

export class YamlLoader {
  /**
   * Load a workflow from a YAML file.
   * Performs env variable substitution and uses the step registry to build Step instances.
   */
  static loadWorkflowFromFile(filePath: string, registry: StepRegistry): Workflow {
    const contents = fs.readFileSync(filePath, 'utf-8');
    const data: any = yaml.load(contents);
    const substituted = substituteEnv(data);
    if (!substituted || !Array.isArray(substituted.steps)) {
      throw new Error('Invalid workflow YAML: missing steps');
    }
    const steps = substituted.steps.map((stepDef: any) => {
      const StepClass = registry.get(stepDef.type);
      if (!StepClass) {
        throw new Error(`Unregistered step type: ${stepDef.type}`);
      }
      return new StepClass(stepDef.config || {});
    });
    return new Workflow(substituted.name || filePath, steps);
  }
}
