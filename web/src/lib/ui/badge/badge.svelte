<script lang="ts" module>
	import { type VariantProps, tv } from "tailwind-variants";

	// Neutral base only: StatusPill (domain layer) supplies the tone classes.
	export const badgeVariants = tv({
		base: "inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap rounded-full border border-transparent bg-muted px-2 text-xs font-medium text-foreground [&>svg]:pointer-events-none [&>svg]:size-3",
	});

	export type BadgeVariants = VariantProps<typeof badgeVariants>;
</script>

<script lang="ts">
	import { cn, type WithElementRef } from "$lib/utils.js";
	import type { HTMLAnchorAttributes } from "svelte/elements";

	let {
		ref = $bindable(null),
		href,
		class: className,
		children,
		...restProps
	}: WithElementRef<HTMLAnchorAttributes> = $props();
</script>

<svelte:element
	this={href ? "a" : "span"}
	bind:this={ref}
	data-slot="badge"
	{href}
	class={cn(badgeVariants(), className)}
	{...restProps}
>
	{@render children?.()}
</svelte:element>
