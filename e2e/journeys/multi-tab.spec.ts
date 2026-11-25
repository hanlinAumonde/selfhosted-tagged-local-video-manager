import { expect, test } from '@playwright/test';
import { editVideo, openDirectory, rowMenu } from '../support/file-browser';

/*
  Tabs of the app tell each other about changes over a BroadcastChannel; the tab that
  hears of one fetches the new state itself. Uses only the seeded "sync" directory of
  Local-resource/Resource-1.
*/

test('a video edited in one tab is updated on the player page open in another', async ({ page: tabA, context }) => {
  /*
    Given Local-resource/Resource-1/sync holds "letter.mp4"
    And tab B shows the player page of "letter"
    When the user, in tab A, edits "letter" in the file browser: title "Love letter", tag "mail"
    Then tab B shows title "Love letter" and tag "mail" without being reloaded
  */
  await openDirectory(tabA, 'Local-resource', 'Resource-1', 'sync');
  const [tabB] = await Promise.all([context.waitForEvent('page'), rowMenu(tabA, 'letter', 'Play Video')]);
  await expect(tabB.getByRole('heading', { name: 'letter', exact: true })).toBeVisible();
  let reloaded = false;
  tabB.on('framenavigated', frame => { if (frame === tabB.mainFrame()) reloaded = true; });

  await editVideo(tabA, 'letter', { title: 'Love letter', addTags: ['mail'] });

  await expect(tabB.getByRole('heading', { name: 'Love letter', exact: true })).toBeVisible();
  await expect(tabB.getByText('Tags:').locator('xpath=following-sibling::a')).toHaveText(['mail']);
  expect(reloaded, 'tab B was not reloaded').toBe(false);
});
