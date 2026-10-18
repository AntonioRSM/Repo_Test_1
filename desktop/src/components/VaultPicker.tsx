import { Dropdown, Field, Option } from "@fluentui/react-components";
import { useStore } from "../store";

export function VaultPicker({ value, onChange }: { value: string | undefined; onChange: (id: string) => void }) {
  const { vaults } = useStore();
  const current = vaults.find((v) => v.id === value);
  return (
    <Field label="Vault">
      <Dropdown
        value={current?.name ?? ""}
        selectedOptions={value ? [value] : []}
        onOptionSelect={(_, d) => d.optionValue && onChange(d.optionValue)}
        placeholder="Scegli un Vault"
        style={{ minWidth: 260 }}
      >
        {vaults.map((v) => (
          <Option key={v.id} value={v.id} text={v.name}>
            {v.name} ({v.stats.vectors} chunk)
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}
