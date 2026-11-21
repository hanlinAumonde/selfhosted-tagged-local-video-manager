import { expect, test } from '@playwright/test';
import { content, openDirectory, row } from '../support/file-browser';

/*
  Migration runs in the worker process and reports back only through GraphQL
  subscriptions, so this journey is also the check that WebSockets get through nginx.
  Uses only the seeded "migration" directories of Local-resource/Resource-1 and -2.
*/

test('a video migrated to another mount leaves the listing on its own and arrives there', async ({ page }) => {
  /*
    Given Local-resource/Resource-1/migration holds "traveller.mp4"
    And Local-resource/Resource-2/migration holds "resident.mp4"
    When the user opens Local-resource / Resource-1 / migration in the file browser
    And migrates "traveller" to Local-resource / Resource-2 / migration
    Then the preflight check says all checks passed
    When the user starts the migration
    Then the migration's completion reaches the page over the WebSocket
    And "traveller" leaves the listing without the page being reloaded
    When the user opens the management page
    Then the task for "traveller" is shown as completed
    When the user opens Local-resource / Resource-2 / migration in the file browser
    Then "resident" and "traveller" are listed
  */
  await openDirectory(page, 'Local-resource', 'Resource-1', 'migration');
  const traveller = content(page).getByText('traveller', { exact: true });
  await expect(traveller).toBeVisible();

  // The last button of a row opens its menu.
  await row(page, 'traveller').getByRole('button').last().click();
  await page.getByRole('menuitem', { name: 'Migrate' }).click();
  const panel = page.getByRole('dialog');
  for (const directory of ['Local-resource', 'Resource-2', 'migration']) {
    await panel.getByRole('button', { name: directory, exact: true }).click();
  }
  await panel.getByRole('button', { name: 'Select this directory' }).click();
  await panel.getByRole('button', { name: 'Preflight Check' }).click();
  await expect(panel.getByText('All checks passed. Ready to migrate.')).toBeVisible();

  // Nothing the user sees depends on the WebSocket alone: a file this small is copied
  // before the dialog closes, and closing it lists the directory afresh anyway. So the
  // frame itself is checked, or a broken nginx upgrade or progress relay would pass.
  let completedOverWebSocket = false;
  page.on('websocket', socket => socket.on('framereceived', frame => {
    if (String(frame.payload).includes('"status":"COMPLETED"')) completedOverWebSocket = true;
  }));
  let reloaded = false;
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) reloaded = true; });
  await panel.getByRole('button', { name: 'Start Migration' }).click();
  await expect.poll(() => completedOverWebSocket, {
    message: 'a COMPLETED frame arrived over the WebSocket',
    timeout: 15_000,
  }).toBe(true);
  await expect(traveller).toHaveCount(0);
  expect(reloaded, 'the page was not reloaded').toBe(false);

  await page.goto('/management');
  const task = content(page).locator('app-migration-task-list .shadow')
    .filter({ has: page.getByText('traveller', { exact: true }) });
  await expect(task).toContainText('Completed');

  await openDirectory(page, 'Local-resource', 'Resource-2', 'migration');
  await expect(row(page, 'resident')).toBeVisible();
  await expect(row(page, 'traveller')).toBeVisible();
});
