import { Step } from '../../core/Step';
import { Logger } from '../../core/Logger';

interface JiraAdapterConfig {
  baseUrl: string;
  username: string;
  apiToken: string;
  issueKeyContextField?: string;
}

/**
 * JiraAdapter fetches a defect by key using the Jira REST API and injects parsed fields into the workflow context.
 */
export class JiraAdapter implements Step {
  static type = 'jira';
  private config: JiraAdapterConfig;

  constructor(config: JiraAdapterConfig) {
    this.config = config;
  }

  async run(context: any): Promise<void> {
    const issueKey = context[this.config.issueKeyContextField || 'issueKey'];
    if (!issueKey) {
      throw new Error('JiraAdapter: issue key not found in context');
    }
    const url = `${this.config.baseUrl.replace(/\/$/, '')}/rest/api/2/issue/${issueKey}`;
    // Basic auth header
    const auth = Buffer.from(`${this.config.username}:${this.config.apiToken}`).toString('base64');
    const response = await fetch(url, {
      headers: {
        'Authorization': `Basic ${auth}`,
        'Accept': 'application/json',
      },
    });
    if (!response.ok) {
      throw new Error(`JiraAdapter: failed to fetch issue ${issueKey}: ${response.status} ${response.statusText}`);
    }
    const data: any = await response.json();
    const fields = data.fields || {};
    context.jira = {
      key: data.key,
      summary: fields.summary,
      description: fields.description,
      priority: fields.priority?.name,
      components: (fields.components || []).map((c: any) => c.name),
      custom: fields.customfield_10000 ?? undefined,
    };
  }
}
