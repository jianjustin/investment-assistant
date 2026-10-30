<script lang="ts" module>
	import { type VariantProps, tv } from "tailwind-variants";

	export const alertVariants = tv({
		base: "group/alert relative grid w-full gap-0.5 rounded-md border px-3 py-2 text-left text-sm has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg:not([class*='size-'])]:size-4",
		variants: {
			variant: {
				info: "border-info/40 bg-info/10 text-foreground *:[svg]:text-info",
				warn: "border-warn/40 bg-warn/10 text-foreground *:[svg]:text-warn",
				danger: "border-destructive/40 bg-destructive/10 text-foreground *:[svg]:text-destructive",
			},
		},
		defaultVariants: {
			variant: "info",
		},
	});

	export type AlertVariant = VariantProps<typeof alertVariants>["variant"];
</script>

<script lang="ts">
	import { cn, type WithElementRef } from "$lib/utils.js";
	import type { HTMLAttributes } from "svelte/elements";

	let {
		ref = $bindable(null),
		class: className,
		variant = "info",
		role,
		children,
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLDivElement>> & {
		variant?: AlertVariant;
	} = $props();
</script>

<div
	bind:this={ref}
	data-slot="alert"
	role={role ?? (variant === "info" ? "status" : "alert")}
	class={cn(alertVariants({ variant }), className)}
	{...restProps}
>
	{@render children?.()}
</div>
