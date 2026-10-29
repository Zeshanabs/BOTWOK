"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { useCreateBrand } from "../hooks";
import type { Brand } from "../types";
import { TimezoneInput, browserTimezone } from "./timezone-input";

function normalizeUrl(u: string): string | null {
  const t = u.trim();
  if (!t) return null;
  return /^https?:\/\//i.test(t) ? t : `https://${t}`;
}

/** POST /brands {name, industry, website, timezone, description}. */
export function BrandBasicsForm({ onCreated, submitLabel = "Create brand", footer }: { onCreated: (b: Brand) => void; submitLabel?: string; footer?: React.ReactNode }) {
  const create = useCreateBrand();
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [website, setWebsite] = useState("");
  const [timezone, setTimezone] = useState(browserTimezone);
  const [description, setDescription] = useState("");
  const errors = problemFieldErrors(create.error);

  return (
    <form className="space-y-4" onSubmit={(e) => {
      e.preventDefault();
      create.mutate({ name: name.trim(), industry: industry.trim() || null, website: normalizeUrl(website), timezone: timezone.trim() || "UTC", description: description.trim() || null }, { onSuccess: onCreated });
    }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="b-name">Brand name</Label>
          <Input id="b-name" value={name} onChange={(e) => setName(e.target.value)} required aria-invalid={!!errors.name} />
          <FieldError errors={errors} name="name" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b-industry">Industry</Label>
          <Input id="b-industry" value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. Specialty coffee" aria-invalid={!!errors.industry} />
          <FieldError errors={errors} name="industry" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b-web">Website</Label>
          <Input id="b-web" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="acme.com" inputMode="url" aria-invalid={!!errors.website} />
          <FieldError errors={errors} name="website" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b-tz">Timezone</Label>
          <TimezoneInput id="b-tz" value={timezone} onChange={setTimezone} invalid={!!errors.timezone} />
          <FieldError errors={errors} name="timezone" />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="b-desc">One-line description <span className="font-normal text-muted-foreground">(optional)</span></Label>
        <Textarea id="b-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} aria-invalid={!!errors.description} />
        <FieldError errors={errors} name="description" />
      </div>
      <FormError error={Object.keys(errors).length ? null : create.error} />
      <div className="flex flex-wrap items-center justify-end gap-2">
        {footer}
        <Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? "Creating…" : submitLabel}</Button>
      </div>
    </form>
  );
}
