<script lang="ts">
  import ConceptTerm from './ConceptTerm.svelte'
  import { ATTACH } from '../knowledge'
  import { CITED_FIELD_TEXT, knowHref, parseKnowRef } from '../growth'
  import type { KnowledgeRefItem } from '../growth'

  // 计划卡与推理视图里的「引用的知识」（spec §6.2）：know:<id>@<版本> + 那一版的标题，点开看引用时的版本；
  // 之后有新版时附「当前已是第 n 版」。
  let { refs }: { refs: KnowledgeRefItem[] } = $props()

  const newer = (item: KnowledgeRefItem): number | null => {
    const cited = parseKnowRef(item.ref)?.version
    return cited != null && item.current_version > cited ? item.current_version : null
  }
</script>

{#if refs?.length}
  <section aria-label="引用的知识" class="text-xs space-y-0.5">
    <p class="text-muted">引用的知识 <ConceptTerm id={ATTACH.myKnowledge.citation}>说明</ConceptTerm></p>
    <ul class="list-disc ml-5">
      {#each refs as item (item.ref)}
        <li><a class="text-accent underline" href={knowHref(item.ref)}>{item.ref}</a> {item.title}{#if item.fields?.length}
            · {item.fields.map(f => CITED_FIELD_TEXT[f] ?? f).join('、')}{/if}{#if newer(item)} · 当前已是第 {newer(item)} 版{/if}</li>
      {/each}
    </ul>
  </section>
{/if}
