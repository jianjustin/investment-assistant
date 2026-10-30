<script lang="ts">
  import * as Tabs from './index'
</script>

<Tabs.Root value="one">
  <Tabs.List aria-label="示例页签">
    <Tabs.Trigger value="one">一</Tabs.Trigger>
    <Tabs.Trigger value="two">二</Tabs.Trigger>
    <Tabs.Trigger value="three">三</Tabs.Trigger>
  </Tabs.List>
  <Tabs.Content value="one">内容一</Tabs.Content>
  <Tabs.Content value="two">内容二</Tabs.Content>
  <Tabs.Content value="three">内容三</Tabs.Content>
</Tabs.Root>
