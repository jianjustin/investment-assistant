<script lang="ts">
	import { cn, type WithElementRef } from "$lib/utils.js";
	import type { HTMLThAttributes } from "svelte/elements";

	let {
		ref = $bindable(null),
		class: className,
		children,
		...restProps
	}: WithElementRef<HTMLThAttributes> = $props();
</script>

<th bind:this={ref} data-slot="table-head" class={cn("h-8 px-2 text-left align-middle text-xs font-medium whitespace-nowrap text-muted-foreground", className)} {...restProps}>
	{@render children?.()}
</th>
