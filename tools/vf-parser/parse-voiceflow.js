#!/usr/bin/env node
/**
 * Voiceflow .vf Export Parser
 *
 * Extracts agent definitions, prompts, and configurations from Voiceflow exports
 * for migration to EMA Production (LiveKit-based voice agent).
 *
 * Usage:
 *   node parse-voiceflow.js <path-to-vf-file> [--output-dir <dir>]
 *
 * Example:
 *   node parse-voiceflow.js ./EMA-export.vf --output-dir ../apps/voice-agent/prompts
 *
 * Output:
 *   - agents.json: All agent definitions with instructions
 *   - settings.json: Voice/ASR settings
 *   - prompts/*.md: Individual agent prompt files
 *   - summary.json: Export summary
 */

const fs = require('fs');
const path = require('path');

class VoiceflowParser {
  constructor(vfFilePath) {
    this.vfFilePath = vfFilePath;
    this.data = null;
    this.agents = {};
    this.settings = {};
  }

  load() {
    console.log(`📂 Loading: ${this.vfFilePath}`);
    const content = fs.readFileSync(this.vfFilePath, 'utf8');
    this.data = JSON.parse(content);
    console.log(`✅ Loaded. Version: ${this.data.version?._version || 'unknown'}`);
    return this;
  }

  extractAgents() {
    console.log('\n🤖 Extracting agents...');

    const programResources = this.data.version?.programResources || {};
    const agents = programResources.agents || {};

    for (const [agentId, agent] of Object.entries(agents)) {
      this.agents[agentId] = {
        id: agentId,
        name: agent.name,
        instructions: agent.instructions,
        settings: agent.settings,
        description: agent.description || '',
      };
      console.log(`   - ${agent.name}`);
    }

    console.log(`\n   Found ${Object.keys(this.agents).length} agents`);
    return this;
  }

  extractSettings() {
    console.log('\n⚙️  Extracting settings...');

    const platformData = this.data.version?.platformData || {};
    const settings = platformData.settings || {};

    this.settings = {
      defaultVoice: settings.defaultVoice,
      locales: settings.locales,
      deepgramASR: settings.deepgramASR,
    };

    console.log(`   Voice: ${this.settings.defaultVoice}`);
    console.log(`   Locales: ${this.settings.locales?.join(', ')}`);

    return this;
  }

  saveOutput(outputDir) {
    console.log(`\n💾 Saving to: ${outputDir}`);

    // Create directories
    fs.mkdirSync(outputDir, { recursive: true });
    fs.mkdirSync(path.join(outputDir, 'prompts'), { recursive: true });

    // Save agents.json
    fs.writeFileSync(
      path.join(outputDir, 'agents.json'),
      JSON.stringify(this.agents, null, 2)
    );
    console.log('   ✓ agents.json');

    // Save settings.json
    fs.writeFileSync(
      path.join(outputDir, 'settings.json'),
      JSON.stringify(this.settings, null, 2)
    );
    console.log('   ✓ settings.json');

    // Save individual prompts
    let promptCount = 0;
    for (const [agentId, agent] of Object.entries(this.agents)) {
      if (agent.instructions) {
        const safeName = agent.name
          .replace(/[^a-zA-Z0-9]/g, '-')
          .replace(/-+/g, '-')
          .replace(/^-|-$/g, '')
          .toLowerCase();

        const promptContent = `# ${agent.name}

> Agent ID: \`${agentId}\`

## Model Settings

\`\`\`json
${JSON.stringify(agent.settings || {}, null, 2)}
\`\`\`

## Instructions

${agent.instructions}
`;

        fs.writeFileSync(
          path.join(outputDir, 'prompts', `${safeName}.md`),
          promptContent
        );
        promptCount++;
      }
    }
    console.log(`   ✓ ${promptCount} prompt files`);

    // Save summary
    const summary = {
      exportDate: new Date().toISOString(),
      sourceFile: path.basename(this.vfFilePath),
      voiceflowVersion: this.data.version?._version,
      counts: {
        agents: Object.keys(this.agents).length,
        promptsGenerated: promptCount,
      },
      agentNames: Object.values(this.agents).map(a => a.name),
    };

    fs.writeFileSync(
      path.join(outputDir, 'summary.json'),
      JSON.stringify(summary, null, 2)
    );
    console.log('   ✓ summary.json');

    return this;
  }

  parse() {
    return this.load()
      .extractAgents()
      .extractSettings();
  }
}

// CLI
function main() {
  const args = process.argv.slice(2);

  if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
    console.log(`
╔══════════════════════════════════════════════════════════════╗
║           Voiceflow → EMA Production Parser                  ║
╚══════════════════════════════════════════════════════════════╝

Usage:
  node parse-voiceflow.js <vf-file> [--output-dir <dir>]

Options:
  --output-dir    Output directory (default: ./vf-output)
  --help, -h      Show this help

Example:
  node parse-voiceflow.js ./EMA-2025-11-25.vf --output-dir ./prompts
`);
    process.exit(0);
  }

  const vfFilePath = args[0];
  let outputDir = './vf-output';

  const outputIdx = args.indexOf('--output-dir');
  if (outputIdx !== -1 && args[outputIdx + 1]) {
    outputDir = args[outputIdx + 1];
  }

  if (!fs.existsSync(vfFilePath)) {
    console.error(`❌ File not found: ${vfFilePath}`);
    process.exit(1);
  }

  try {
    console.log('\n╔══════════════════════════════════════════════════════════════╗');
    console.log('║           Voiceflow → EMA Production Parser                  ║');
    console.log('╚══════════════════════════════════════════════════════════════╝\n');

    const parser = new VoiceflowParser(vfFilePath);
    parser.parse().saveOutput(outputDir);

    console.log('\n✅ Done!\n');
    console.log('Next steps:');
    console.log(`  1. Review prompts in ${outputDir}/prompts/`);
    console.log('  2. Copy needed prompts to apps/voice-agent/prompts/');
    console.log('  3. Update agent.py to use the prompts\n');
  } catch (error) {
    console.error(`❌ Error: ${error.message}`);
    process.exit(1);
  }
}

module.exports = { VoiceflowParser };

if (require.main === module) {
  main();
}
