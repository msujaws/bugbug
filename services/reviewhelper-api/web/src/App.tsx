import { BarChart, LineChart } from "@mantine/charts";
import {
  Badge,
  Card,
  Container,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import {
  DayPoint,
  Group as ReviewerGroup,
  Histograms,
  Revision,
  Summary,
  fetchGroups,
  fetchHistograms,
  fetchRevisions,
  fetchSummary,
  fetchTimeseries,
} from "./api";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card withBorder padding="md" radius="md">
      <Text size="xs" c="dimmed" tt="uppercase">
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
    </Card>
  );
}

export function App() {
  const [group, setGroup] = useState<string | undefined>(undefined);
  const [groups, setGroups] = useState<ReviewerGroup[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [hist, setHist] = useState<Histograms | null>(null);
  const [series, setSeries] = useState<DayPoint[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGroups().then(setGroups).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    setError(null);
    Promise.all([
      fetchSummary(group),
      fetchHistograms(group),
      fetchTimeseries(group),
      fetchRevisions(group),
    ])
      .then(([s, h, t, r]) => {
        setSummary(s);
        setHist(h);
        setSeries(t);
        setRevisions(r.items);
      })
      .catch((e) => setError(String(e)));
  }, [group]);

  if (error) return <Container py="xl"><Text c="red">{error}</Text></Container>;
  if (!summary || !hist) return <Container py="xl"><Loader /></Container>;

  const histData = hist.risk.map((_, score) => ({
    score: String(score),
    risk: hist.risk[score],
    complexity: hist.complexity[score],
  }));

  return (
    <Container size="lg" py="xl">
      <Group justify="space-between" mb="lg">
        <Title order={2}>Automated Review Dashboard</Title>
        <Select
          placeholder="All groups"
          clearable
          value={group ?? null}
          onChange={(v) => setGroup(v ?? undefined)}
          data={groups.map((g) => ({
            value: g.slug,
            label: `${g.slug}${g.enabled ? "" : " (off)"}`,
          }))}
        />
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} mb="lg">
        <Kpi label="Requests" value={String(summary.requests)} />
        <Kpi label="Reviewed" value={String(summary.reviewed)} />
        <Kpi label="Coverage" value={`${summary.coverage_pct}%`} />
        <Kpi label="Skipped" value={String(summary.skipped)} />
        <Kpi label="Est. cost" value={`$${summary.estimated_cost_usd.toFixed(2)}`} />
        <Kpi label="Time saved" value={`${summary.time_saved_hours} h`} />
        <Kpi
          label="Median risk / cx"
          value={`${summary.median_risk ?? "–"} / ${summary.median_complexity ?? "–"}`}
        />
        <Kpi
          label="Feedback +/-"
          value={`${summary.feedback.up} / ${summary.feedback.down}`}
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }} mb="lg">
        <Card withBorder radius="md" padding="md">
          <Text fw={600} mb="sm">Score distribution</Text>
          <BarChart
            h={240}
            data={histData}
            dataKey="score"
            series={[
              { name: "risk", color: "red.6" },
              { name: "complexity", color: "blue.6" },
            ]}
          />
        </Card>
        <Card withBorder radius="md" padding="md">
          <Text fw={600} mb="sm">Daily throughput</Text>
          <LineChart
            h={240}
            data={series}
            dataKey="date"
            series={[
              { name: "requests", color: "gray.6" },
              { name: "reviewed", color: "green.6" },
              { name: "skipped", color: "orange.6" },
            ]}
            curveType="linear"
          />
        </Card>
      </SimpleGrid>

      <Card withBorder radius="md" padding="md">
        <Text fw={600} mb="sm">Recent revisions</Text>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Revision</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Risk</Table.Th>
              <Table.Th>Complexity</Table.Th>
              <Table.Th>Reason</Table.Th>
              <Table.Th>Cost</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {revisions.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>D{r.revision_id}</Table.Td>
                <Table.Td>
                  <Badge variant="light">{r.status}</Badge>
                </Table.Td>
                <Table.Td>{r.risk ?? "–"}</Table.Td>
                <Table.Td>{r.complexity ?? "–"}</Table.Td>
                <Table.Td>{r.skipped_reason ?? ""}</Table.Td>
                <Table.Td>${r.estimated_cost_usd.toFixed(3)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Container>
  );
}
