import { StepRegistry } from './StepRegistry';
import { JiraAdapter } from '../adapters/jira/JiraAdapter';
import { PostmanAdapter } from '../adapters/postman/PostmanAdapter';
import { MongoDBAdapter } from '../adapters/mongodb/MongoDBAdapter';
import { GenAIPlanner } from '../adapters/genai/GenAIPlanner';

const registry = new StepRegistry();

// Register step types
registry.register('jira', JiraAdapter as any);
registry.register('postman', PostmanAdapter as any);
registry.register('mongodb', MongoDBAdapter as any);
registry.register('genai', GenAIPlanner as any);

export { registry };
