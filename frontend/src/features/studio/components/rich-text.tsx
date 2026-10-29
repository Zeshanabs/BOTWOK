"use client";
import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Bold, Heading2, Italic, Link2, List, ListOrdered, Quote, Strikethrough, Unlink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { mdToHtml, pmToMd, type PMNode } from "../markdown";

const PROSE = "min-h-[160px] px-3 py-2 text-sm leading-relaxed outline-none [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_h2]:mt-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1";

/** Markdown-backed Tiptap (StarterKit) body editor with a compact toolbar. Emits markdown. */
export function RichTextEditor({ value, onChange, ariaLabel = "Body", placeholder = "Write the body…", readOnly, invalid, className }: {
  value: string; onChange: (md: string) => void; ariaLabel?: string; placeholder?: string; readOnly?: boolean; invalid?: boolean; className?: string;
}) {
  const lastEmitted = useRef<string | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; });
  const [initial] = useState(() => mdToHtml(value));
  const editor = useEditor({
    extensions: [StarterKit.configure({ heading: { levels: [2, 3] }, link: { openOnClick: false, autolink: true } })],
    content: initial,
    immediatelyRender: false,
    editable: !readOnly,
    editorProps: { attributes: { class: PROSE, "aria-label": ariaLabel, role: "textbox", "aria-multiline": "true" } },
    onUpdate: ({ editor: ed }) => {
      const md = pmToMd(ed.getJSON() as PMNode);
      lastEmitted.current = md;
      onChangeRef.current(md);
    },
  });

  // Push external changes (server sync, AI apply, restore) into the editor without echoing an update.
  useEffect(() => {
    if (!editor) return;
    if (lastEmitted.current === null) { lastEmitted.current = value; return; }
    if (value !== lastEmitted.current) {
      lastEmitted.current = value;
      editor.commands.setContent(mdToHtml(value), { emitUpdate: false });
    }
  }, [value, editor]);

  useEffect(() => { editor?.setEditable(!readOnly); }, [editor, readOnly]);

  const state = useEditorState({
    editor,
    selector: ({ editor: ed }) => ed ? {
      bold: ed.isActive("bold"), italic: ed.isActive("italic"), strike: ed.isActive("strike"), h2: ed.isActive("heading", { level: 2 }),
      ul: ed.isActive("bulletList"), ol: ed.isActive("orderedList"), quote: ed.isActive("blockquote"), link: ed.isActive("link"), empty: ed.isEmpty,
    } : null,
  });
  const [linkOpen, setLinkOpen] = useState(false);
  const [href, setHref] = useState("");

  const tool = (label: string, active: boolean | undefined, onClick: () => void, Icon: typeof Bold) => (
    <Button key={label} type="button" size="icon-xs" variant={active ? "secondary" : "ghost"} aria-label={label} aria-pressed={!!active} title={label}
            onMouseDown={(e) => e.preventDefault()} onClick={onClick} disabled={readOnly || !editor}>
      <Icon />
    </Button>
  );

  return (
    <div className={cn("rounded-md border bg-background focus-within:ring-[3px] focus-within:ring-ring/50", invalid && "border-destructive", className)}>
      <div className="flex flex-wrap items-center gap-0.5 border-b px-1.5 py-1" role="toolbar" aria-label="Formatting">
        {tool("Bold", state?.bold, () => editor?.chain().focus().toggleBold().run(), Bold)}
        {tool("Italic", state?.italic, () => editor?.chain().focus().toggleItalic().run(), Italic)}
        {tool("Strikethrough", state?.strike, () => editor?.chain().focus().toggleStrike().run(), Strikethrough)}
        {tool("Heading", state?.h2, () => editor?.chain().focus().toggleHeading({ level: 2 }).run(), Heading2)}
        {tool("Bulleted list", state?.ul, () => editor?.chain().focus().toggleBulletList().run(), List)}
        {tool("Numbered list", state?.ol, () => editor?.chain().focus().toggleOrderedList().run(), ListOrdered)}
        {tool("Quote", state?.quote, () => editor?.chain().focus().toggleBlockquote().run(), Quote)}
        <Popover open={linkOpen} onOpenChange={(o) => { setLinkOpen(o); if (o) setHref(String(editor?.getAttributes("link").href ?? "")); }}>
          <PopoverTrigger asChild>
            <Button type="button" size="icon-xs" variant={state?.link ? "secondary" : "ghost"} aria-label="Link" title="Link" disabled={readOnly || !editor} onMouseDown={(e) => e.preventDefault()}><Link2 /></Button>
          </PopoverTrigger>
          <PopoverContent className="w-72" align="start">
            <form className="flex gap-2" onSubmit={(e) => {
              e.preventDefault();
              const url = href.trim();
              if (url) editor?.chain().focus().extendMarkRange("link").setLink({ href: /^https?:\/\//.test(url) ? url : `https://${url}` }).run();
              setLinkOpen(false);
            }}>
              <Input autoFocus value={href} onChange={(e) => setHref(e.target.value)} placeholder="https://…" aria-label="Link URL" className="h-8" />
              <Button size="sm" type="submit">Set</Button>
            </form>
          </PopoverContent>
        </Popover>
        {state?.link && tool("Remove link", false, () => editor?.chain().focus().unsetLink().run(), Unlink)}
        <span className="ml-auto pr-1 text-[11px] text-muted-foreground">Markdown</span>
      </div>
      <div className="relative">
        {state?.empty && <span className="pointer-events-none absolute left-3 top-2 text-sm text-muted-foreground">{placeholder}</span>}
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
